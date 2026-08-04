"""
Browser tools — Freya's hands on a real Chromium window.

Runs on `core/browser` (ours, from scratch) instead of the browser-use library.
What changed for callers: nothing in the tool contract. `browser_task` still
takes a plain-language task, still runs in the background, still reports back
out loud through the proactive channel.

What changed underneath:
  • The whole agent loop is ours — see core/browser/agent.py.
  • DuckDuckGo, not the library's search of choice.
  • The mouse arcs, the typing has rhythm, the scrolling has momentum
    (core/browser/human.py).
  • One persistent profile and one browser thread, shared by every caller,
    so logins survive and Chromium is never opened twice.

Two extra tools sit alongside it:
  • `browser_research` — the researcher sub-agent's entry point. Blocking and
    returning its findings, because a sub-agent is already in the background and
    needs the answer in hand to write its briefing.
  • `browser_open` — a direct "open this page and read it to me", no LLM loop
    and no quota, for when Freya just wants to look at a page.
"""

import asyncio
import itertools
import threading
import time

from core import runtime
from core.registry import tool, OBJ, P, STR, INT

_counter = itertools.count(1)
_jobs: dict[str, dict] = {}

_QUOTA = "__QUOTA__"


def _is_quota(text) -> bool:
    t = str(text).lower()
    return "429" in t or "resource_exhausted" in t or "quota" in t


def _emit_threadsafe(main_loop: asyncio.AbstractEventLoop, coro):
    """Fire an async runtime call from a worker thread onto the live session's
    loop. Fire-and-forget — the worker never blocks on the result."""
    try:
        asyncio.run_coroutine_threadsafe(coro, main_loop)
    except Exception as e:
        print(f"  [browser] cross-loop emit failed: {e}")


async def _run_task(task: str, config: dict, on_step=None) -> str:
    """One browsing task on the browser loop. Returns the agent's answer."""
    from core.browser.agent import BrowserAgent
    agent = BrowserAgent(task, config, on_step=on_step)
    return await agent.run()


def _run_job(job_id: str, task: str, config: dict, main_loop: asyncio.AbstractEventLoop):
    """Background job wrapper: submit to the browser thread, wait, report.

    This runs on its own throwaway thread purely so `browser_task` can return
    immediately; the actual browsing happens on the single shared browser loop.
    """
    from core.browser.driver import BrowserLoop

    async def on_step(step: int, action: str, detail: str):
        job = _jobs.get(job_id)
        if job is not None:
            job["step"] = f"{action} ({step})"
        _emit_threadsafe(main_loop, runtime.emit("browser", {
            "id": job_id, "status": "running", "task": task,
            "step": action, "detail": detail,
        }))

    _emit_threadsafe(main_loop, runtime.emit(
        "browser", {"id": job_id, "status": "running", "task": task}))

    try:
        future = BrowserLoop.get().submit(_run_task(task, config, on_step))
        result = future.result()
    except Exception as e:
        result = _QUOTA if _is_quota(e) else f"The browser hit an error: {e}"

    _jobs[job_id].update(status="done", result=result, step=None)
    _emit_threadsafe(main_loop, runtime.emit("browser", {"id": job_id, "status": "done"}))

    if result == _QUOTA:
        _emit_threadsafe(main_loop, runtime.inject(
            "I couldn't finish browsing — I've hit the free-tier quota on the Gemini API "
            "for web tasks. Tell Ihan: try again later, or add billing / a second API key to "
            "lift the limit. For quick facts I can still search the web instead."
        ))
    else:
        _emit_threadsafe(main_loop, runtime.inject(
            f"The browser finished your task '{task}'. Result: {str(result)[:1500]}"
        ))


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "browser_task",
    "Drive a real Chromium browser like a person: search, click through pages, fill forms, log "
    "in, navigate a web app, add to cart, work through a multi-step site. It searches with "
    "DuckDuckGo, reads the pages it opens, and runs in the background — reporting back out loud "
    "when done. "
    "For a quick fact or a one-line lookup use web_search instead: it's faster and quota-free. "
    "For headlines use get_world_news / get_news. Use the browser when the task genuinely needs "
    "reading real pages or interacting with them.",
    OBJ({"task": P(STR, "The web task in plain language, e.g. 'find the top 3 GPUs under $500 "
                        "with current prices' or 'log into my account and check the order status'")},
        ["task"]),
    gate="browser.enabled",
)
async def browser_task(args, ctx) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return "Give me a web task to do."
    job_id = f"web-{next(_counter)}"
    # `started` feeds the dashboard's live job list (GET /agents), which sorts
    # by start time and shows how long each worker has been going.
    _jobs[job_id] = {"task": task, "status": "running", "result": None,
                     "started": time.time()}
    main_loop = asyncio.get_running_loop()
    threading.Thread(
        target=_run_job, args=(job_id, task, ctx.config, main_loop),
        daemon=True, name=f"browser-job-{job_id}",
    ).start()
    return (f"On it — I've opened the browser and started working on: {task}. "
            "I'll tell you what I find when it's done.")


@tool(
    "browser_research",
    "Research something on the live web with the real browser and WAIT for the findings. "
    "Searches DuckDuckGo, opens the actual pages, reads them, and returns what it found. "
    "Slower than web_search but far deeper — it reads full articles instead of snippets and "
    "follows links. Use this when you need real substance: comparing sources, current details, "
    "anything where a search snippet isn't enough.",
    OBJ({"topic": P(STR, "What to research, as a full question or instruction"),
         "depth": P(INT, "Roughly how many actions to spend on it (default 12, max 30). Each "
                         "search, click, scroll and read costs one.")},
        ["topic"]),
    gate="browser.enabled",
)
async def browser_research(args, ctx) -> str:
    topic = (args.get("topic") or "").strip()
    if not topic:
        return "What should I research?"

    from core.browser.driver import BrowserLoop

    config = dict(ctx.config or {})
    bcfg = dict(config.get("browser", {}))
    # Floor of 6: search, open, read, open, read, finish is the shortest run
    # that can honour "read two sources" — below that it always runs out.
    bcfg["max_steps"] = max(6, min(30, int(args.get("depth") or 12)))
    config["browser"] = bcfg

    task = (f"Research this thoroughly and report the findings with sources: {topic}. "
            "Open and read at least two different pages before answering.")

    await ctx.emit("browser", {"id": "research", "status": "running", "task": topic})
    try:
        future = BrowserLoop.get().submit(_run_task(task, config))
        # Don't block the calling event loop while the browser thread works.
        result = await asyncio.wrap_future(future)
    except Exception as e:
        if _is_quota(e):
            return ("I hit the Gemini free-tier quota while browsing. Try web_search instead, "
                    "or come back to this later.")
        return f"The browser research failed: {e}"
    finally:
        await ctx.emit("browser", {"id": "research", "status": "done"})

    return f"Research findings on '{topic}':\n{result}"


@tool(
    "browser_open",
    "Open a page in the real browser and read it out — no LLM loop, no quota. Use when you "
    "already know the URL and just want to see what's on it, or when web_fetch was blocked by a "
    "site that needs real JavaScript to render.",
    OBJ({"url": P(STR, "The URL to open")}, ["url"]),
    gate="browser.enabled",
)
async def browser_open(args, ctx) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        return "Give me a URL to open."

    from core.browser.driver import BrowserLoop, get_browser

    async def _open():
        browser = await get_browser(ctx.config)
        opened = await browser.goto(url)
        text = await browser.read_page(max_chars=6000)
        return f"{opened}\n\n{text}"

    try:
        return await asyncio.wrap_future(BrowserLoop.get().submit(_open()))
    except Exception as e:
        return f"Couldn't open that page: {e}"


@tool(
    "browser_status",
    "Check what the background browser jobs are doing.",
    OBJ(),
    gate="browser.enabled",
)
def browser_status(args, ctx) -> str:
    if not _jobs:
        return "The browser hasn't been given any jobs yet."
    lines = []
    for jid, j in _jobs.items():
        age = int(time.time() - j["started"])
        if j["status"] == "done":
            lines.append(f"{jid}: done — {str(j['result'])[:200]}")
        else:
            step = f", currently: {j['step']}" if j.get("step") else ""
            lines.append(f"{jid}: still working ({age}s) on '{j['task'][:60]}'{step}")
    return "\n".join(lines)
