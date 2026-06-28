"""
browser-use agent — Freya autonomously drives a real Chromium browser.

Wraps the browser-use library (github.com/browser-use/browser-use): an LLM-driven agent that
navigates real web pages with Playwright — clicking, typing, reading, multi-step. Freya hands
it a natural-language task ("find the cheapest flight to Tokyo next month and the price"); it
runs in the background and reports the answer out loud via the proactive channel.

The browser agent uses its own Gemini model (ChatGoogle) so it can read page screenshots/DOM
independently of the live voice model. Heavy + slow, so it always runs as a background task.
"""

import asyncio
import itertools
import os

from config import get_agent_api_key
from core import runtime
from core.registry import tool, OBJ, P, STR

_counter = itertools.count(1)
_jobs: dict[str, dict] = {}

_QUOTA = "__QUOTA__"


def _is_quota(text) -> bool:
    t = str(text).lower()
    return "429" in t or "resource_exhausted" in t or "quota" in t


async def _run_browser(job_id: str, task: str, config: dict):
    bcfg = (config or {}).get("browser", {})
    model = bcfg.get("llm_model", "gemini-2.5-flash")
    fallback_model = bcfg.get("fallback_model", "gemini-2.5-flash-lite")
    max_steps = int(bcfg.get("max_steps", 25))
    result = "(no result)"
    try:
        from browser_use import Agent, ChatGoogle
        key = get_agent_api_key()  # secondary key — spares the voice quota
        os.environ.setdefault("GOOGLE_API_KEY", key)

        def _mk(m):
            try:
                return ChatGoogle(model=m, api_key=key)
            except TypeError:
                return ChatGoogle(model=m)  # older signature reads env

        llm = _mk(model)
        # A fallback on a DIFFERENT model = a separate daily quota pool, so a 429 on the
        # primary doesn't kill the task.
        try:
            agent = Agent(task=task, llm=llm, fallback_llm=_mk(fallback_model))
        except TypeError:
            agent = Agent(task=task, llm=llm)

        await runtime.emit("browser", {"id": job_id, "status": "running", "task": task})
        history = await agent.run(max_steps=max_steps)
        try:
            final = history.final_result()
        except Exception:
            final = None
        if final:
            result = final
        elif _is_quota(history):
            result = _QUOTA
        else:
            result = str(history)
    except Exception as e:
        result = _QUOTA if _is_quota(e) else f"The browser agent hit an error: {e}"

    _jobs[job_id].update(status="done", result=result)
    await runtime.emit("browser", {"id": job_id, "status": "done"})
    if result == _QUOTA:
        await runtime.inject(
            "I couldn't finish browsing — I've hit the daily free-tier quota on the Gemini API "
            "for web tasks. Tell Ihan: try again later, or add billing / a second API key to lift "
            "the limit. For quick facts I can still read the news instead."
        )
    else:
        await runtime.inject(f"The browser finished your task '{task}'. Result: {str(result)[:1200]}")


@tool(
    "browser_task",
    "Drive a real Chromium browser for INTERACTIVE, multi-step web tasks: log in, fill a form, "
    "click through a site, add to cart, navigate a web app, or anything that needs real clicking. "
    "It runs in the background and reports back out loud. "
    "For simple information lookups ('search the web', 'look something up', 'what's the latest on "
    "X', check a fact) use web_search instead — it's faster and quota-free. "
    "For news use get_world_news / get_news. Only use this browser for tasks that truly need "
    "interacting with a page.",
    OBJ({"task": P(STR, "The web task or search in plain language, e.g. 'search the latest Python "
                        "version' or 'find the top 3 GPUs under $500 with prices'")}, ["task"]),
    gate="browser.enabled",
)
async def browser_task(args, ctx) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return "Give me a web task to do."
    job_id = f"web-{next(_counter)}"
    _jobs[job_id] = {"task": task, "status": "running", "result": None}
    asyncio.create_task(_run_browser(job_id, task, ctx.config))
    return (f"On it — I've opened a browser and started working on: {task}. "
            "I'll tell you what I find when it's done.")
