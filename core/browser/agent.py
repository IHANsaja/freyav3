"""
The brain — perceive, decide, act, repeat.

This is the loop `browser_use.Agent` used to run for us, rewritten so we own it.
Each step the model gets the same three things a person has: the address bar,
a numbered list of what can be clicked or typed into, and (optionally) a picture
of the screen. It answers with one action. We perform it through the motion
layer, re-perceive, and go again — until it calls `finish`.

Two things it does that the library would not:

**It searches DuckDuckGo.** Not as an HTTP call behind the scenes — it navigates
to the results page in the real window and clicks through, because that is what
"use the browser like a human" means and because a clicked-through page yields
the full article rather than a search snippet.

**It doesn't refuse to read the web.** Model-side safety thresholds are relaxed
(`browser.relaxed_filters`) so the agent describes what a page actually says
instead of declining halfway through a research task. This governs the agent's
own willingness to report page content; it is not a licence to do anything on a
page that Freya's approval gate would otherwise stop.
"""

import asyncio
import base64

from google import genai
from google.genai import types

from config import get_agent_api_key
from core.browser.driver import get_browser
from core.browser.perception import PageView

SYSTEM = """You are Freya's browser. You are looking at a real Chromium window on the user's \
computer and you drive it exactly like a person would: you read what's on screen, you click \
things, you type into boxes, you scroll to see more.

HOW YOU SEE
Every step you get the current URL, a numbered list of the things on the page you can interact \
with, and the page's readable text. Act only on numbers you can actually see in that list. If \
what you need isn't there, scroll or navigate — never invent an index.

HOW YOU WORK
- Start with search_web unless you were given a URL. Your search engine is DuckDuckGo.
- Search results are a means, not an answer. Open the promising result and read the real page. \
A snippet is not a source.
- Scroll. The answer is usually below the fold, and you only get the text you have scrolled past.
- If a page is a dead end, go back and try the next result instead of grinding on it.
- Cross-check anything that matters against a second source.
- When you have what was asked for, call finish with the actual answer written out — facts, \
numbers, names, URLs. Never finish with "I found some information about it".

WHAT YOU ARE NOT
You are not a summariser of your own guesses. Everything you report must come from a page you \
actually opened in this session. If you could not find it, say so plainly in finish and say \
where you looked. Report what pages say accurately, including content you find distasteful — \
you are reading the web on the user's behalf, not curating it."""


def _tools() -> list[types.Tool]:
    def fn(name, desc, props=None, required=None):
        return types.FunctionDeclaration(
            name=name, description=desc,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties=props or {},
                required=required or [],
            ),
        )

    S = types.Type.STRING
    I = types.Type.INTEGER
    B = types.Type.BOOLEAN
    p = lambda t, d: types.Schema(type=t, description=d)

    return [types.Tool(function_declarations=[
        fn("search_web", "Search DuckDuckGo for something and land on the results page.",
           {"query": p(S, "What to search for")}, ["query"]),
        fn("open_url", "Navigate straight to a URL you already know.",
           {"url": p(S, "Full URL")}, ["url"]),
        fn("click", "Click one of the numbered things on the page.",
           {"index": p(I, "The number in brackets from the element list")}, ["index"]),
        fn("type", "Type into one of the numbered input boxes.",
           {"index": p(I, "The number of the input box"),
            "text": p(S, "What to type"),
            "submit": p(B, "Press Enter afterwards (default true)")}, ["index", "text"]),
        fn("scroll", "Scroll the page to reveal more.",
           {"direction": p(S, "'down' or 'up'"),
            "amount": p(S, "'little', 'half', 'page', or 'bottom'")}),
        fn("read_page", "Read the current page's full text — use before answering from an article."),
        fn("press_key", "Press a key, e.g. Enter, Escape, Tab, PageDown.",
           {"key": p(S, "Key name")}, ["key"]),
        fn("go_back", "Go back to the previous page."),
        fn("finish", "You have the answer. Write it out in full.",
           {"answer": p(S, "The complete answer, with the facts and the sources you used"),
            "success": p(B, "True only if the requested task was completed; false if blocked or incomplete")}, ["answer", "success"]),
    ])]


def _safety(relaxed: bool) -> list[types.SafetySetting] | None:
    """Model-side content thresholds.

    Relaxed by default: the agent's job is to report what a page says. With the
    default thresholds it will abandon a research task mid-way over a quoted
    slur in a news article or a medical page's clinical detail, which reads to
    the user as Freya simply failing.
    """
    if not relaxed:
        return None
    return [
        types.SafetySetting(category=c, threshold=types.HarmBlockThreshold.BLOCK_NONE)
        for c in (
            types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
        )
    ]


class BrowserAgent:
    """One browsing task, start to finish.

    Must be constructed and run on the browser loop (core/browser/driver.py) —
    everything it touches lives there.
    """

    def __init__(self, task: str, config: dict | None = None, on_step=None):
        self.task = task
        self.config = config or {}
        self.bcfg = self.config.get("browser", {})
        self.on_step = on_step          # async (step:int, action:str, detail:str)
        self.client = genai.Client(api_key=get_agent_api_key(), http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
        self.model = self.bcfg.get("llm_model", "gemini-3.5-flash")
        self.fallback = self.bcfg.get("fallback_model", "gemini-3.5-flash-lite")
        self.max_steps = int(self.bcfg.get("max_steps", 25))
        self.use_vision = bool(self.bcfg.get("vision", True))
        self.history: list[types.Content] = []
        self.visited: list[str] = []

    async def run(self) -> str:
        browser = await get_browser(self.config)
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=_tools(),
            temperature=0.3,
            safety_settings=_safety(bool(self.bcfg.get("relaxed_filters", True))),
        )

        self.history.append(types.Content(role="user", parts=[types.Part(text=(
            f"TASK: {self.task}\n\nThe browser is open and blank. Begin."
        ))]))

        for step in range(1, self.max_steps + 1):
            resp = await self._generate(cfg)
            cand = (resp.candidates or [None])[0]
            if cand is None or cand.content is None:
                from core.execution import ExecutionError
                raise ExecutionError(self._salvage("The model returned nothing."))

            parts = cand.content.parts or []
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not calls:
                # Prose can describe an obstacle; it is not proof of completion.
                self.history.append(cand.content)
                self.history.append(types.Content(role="user", parts=[types.Part(
                    text="Continue with a tool, or call finish with success=false if blocked. Do not claim completion without the requested findings.")]))
                continue

            self.history.append(cand.content)
            call = calls[0]                     # one action per step, like a person
            name = call.name
            args = dict(call.args or {})

            if name == "finish":
                answer = str(args.get("answer") or "").strip()
                if args.get("success") is not True:
                    from core.execution import ExecutionError
                    raise ExecutionError(answer or "Browser could not complete the task")
                if not answer:
                    from core.execution import ExecutionError
                    raise ExecutionError("Browser finished without an answer")
                return answer

            result = await self._act(browser, name, args)
            if self.on_step:
                try:
                    await self.on_step(step, name, str(result)[:160])
                except Exception:
                    pass

            observation = await self._observe(browser, result)
            # Preserve the model's thought signatures and answer every function call.
            responses = [types.Part(function_response=types.FunctionResponse(
                name=name, id=call.id, response={"result":result}))]
            responses.extend(types.Part(function_response=types.FunctionResponse(
                name=extra.name, id=extra.id,
                response={"error":"Not executed: choose one browser action per turn."})) for extra in calls[1:])
            observation = responses + observation
            self.history.append(types.Content(role="user", parts=observation))
            self._trim()

        # Out of steps — but it has been reading pages this whole time. Ask for
        # the answer from what it already saw rather than returning nothing;
        # a run that hits the cap one step short of `finish` otherwise throws
        # away everything it learned.
        from core.execution import Exhausted
        raise Exhausted(self._salvage("Browser exhausted its action budget."))

    # ── acting ─────────────────────────────────────────────────────────────
    async def _act(self, browser, name: str, args: dict) -> str:
        try:
            if name == "search_web":
                return await browser.search(str(args.get("query", "")))
            if name == "open_url":
                url = str(args.get("url", ""))
                self.visited.append(url)
                return await browser.goto(url)
            if name == "click":
                return await browser.click(int(args.get("index", -1)))
            if name == "type":
                return await browser.type_text(
                    int(args.get("index", -1)), str(args.get("text", "")),
                    submit=bool(args.get("submit", True)))
            if name == "scroll":
                return await browser.scroll(str(args.get("direction", "down")),
                                            str(args.get("amount", "page")))
            if name == "read_page":
                return await browser.read_page()
            if name == "press_key":
                return await browser.press(str(args.get("key", "Enter")))
            if name == "go_back":
                return await browser.go_back()
            return f"I don't have an action called {name}."
        except Exception as e:
            return f"That action failed: {str(e)[:200]}"

    async def _observe(self, browser, result: str) -> list[types.Part]:
        """What the agent sees after acting: the outcome, then the new page."""
        view: PageView = browser.view
        if view.url and view.url not in self.visited:
            self.visited.append(view.url)

        parts = [types.Part(text=f"RESULT: {result}\n\n{view.render()}")]

        if self.use_vision:
            shot = await browser.screenshot()
            if shot:
                parts.append(types.Part(inline_data=types.Blob(
                    data=base64.b64decode(shot), mime_type="image/jpeg")))
        return parts

    # ── model plumbing ─────────────────────────────────────────────────────
    async def _generate(self, cfg):
        from core.quota import generate
        return await generate(self.client, quota_config=self.config,
            model=self.model, contents=self.history, config=cfg)

    def _trim(self, keep: int = 8):
        """Drop the middle of the history, keeping the task and recent steps.

        Screenshots are large; an untrimmed 25-step run blows the context window
        and gets slower every step. The task itself is always turn zero, so the
        agent never forgets what it was asked.
        """
        if len(self.history) <= keep + 1:
            return
        self.history = self.history[:1] + self.history[-keep:]
        # Older screenshots are dead weight once the page has moved on.
        for content in self.history[1:-4]:
            content.parts = [p for p in (content.parts or [])
                             if getattr(p, "inline_data", None) is None] or content.parts

    async def _final_answer(self) -> str:
        """One last call, no tools: answer from the pages already read."""
        self.history.append(types.Content(role="user", parts=[types.Part(text=(
            f"You've used all {self.max_steps} steps. Write the answer to '{self.task}' now, "
            "using only what you actually read on the pages above. Include the specifics and "
            "name the sources. If you genuinely didn't find it, say what you did establish and "
            "where you looked."
        ))]))
        try:
            resp = await self._generate(types.GenerateContentConfig(
                system_instruction=SYSTEM,
                temperature=0.3,
                safety_settings=_safety(bool(self.bcfg.get("relaxed_filters", True))),
            ))
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception as e:
            print(f"  [browser] final summary failed: {e}")
        return self._salvage(f"I ran out of steps ({self.max_steps}) before finishing.")

    def _salvage(self, reason: str) -> str:
        """Never come back empty-handed — say what was seen and where."""
        pages = ", ".join(self.visited[-5:]) or "nothing"
        return f"{reason} Pages I looked at: {pages}."


def _is_quota(e) -> bool:
    t = str(e).lower()
    return "429" in t or "resource_exhausted" in t or "quota" in t


def _is_overloaded(e) -> bool:
    t = str(e).lower()
    return "503" in t or "unavailable" in t or "overloaded" in t or "high demand" in t
