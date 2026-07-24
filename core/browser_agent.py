"""
browser-use agent — Freya autonomously drives a real Chromium browser.

Wraps the browser-use library (github.com/browser-use/browser-use): an LLM-driven agent that
navigates real web pages with Playwright — clicking, typing, reading, multi-step. Freya hands
it a natural-language task ("find the cheapest flight to Tokyo next month and the price"); it
runs in the background and reports the answer out loud via the proactive channel.

The browser agent uses its own Gemini model (ChatGoogle) so it can read page screenshots/DOM
independently of the live voice model. Heavy + slow, so it always runs as a background task —
AND on its own OS thread with its own asyncio event loop (see `_run_browser_thread`). This
isolation matters: browser-use's CDP screenshot/DOM extraction can stall for 10+ seconds under
load (observed directly in logs — ScreenshotWatchdog handler timeouts), and if that work ran on
the SAME event loop as the live voice session (as it did before), those stalls starved the
mic/speaker scheduling and Gemini Live's receive loop, causing audible lag or dead air. Running
it on a dedicated loop means it can stall all it wants without ever blocking audio; the only
cross-thread traffic is two small status callbacks marshaled back via run_coroutine_threadsafe.
"""

import asyncio
import itertools
import os
import threading
import time

from config import get_agent_api_key
from core import runtime
from core.registry import tool, OBJ, P, STR

_counter = itertools.count(1)
_jobs: dict[str, dict] = {}

_QUOTA = "__QUOTA__"


def _is_quota(text) -> bool:
    t = str(text).lower()
    return "429" in t or "resource_exhausted" in t or "quota" in t


def _emit_threadsafe(main_loop: asyncio.AbstractEventLoop, coro):
    """Fire an async runtime call from the worker thread onto the main loop.
    Fire-and-forget: we don't block the worker thread waiting for the result."""
    try:
        asyncio.run_coroutine_threadsafe(coro, main_loop)
    except Exception as e:
        print(f"  [browser_agent] cross-loop emit failed: {e}")


def _run_browser_thread(job_id: str, task: str, config: dict, main_loop: asyncio.AbstractEventLoop):
    """Entry point for the dedicated worker thread. Creates its OWN event loop
    (Proactor, per server.py's process-wide policy) so Playwright/CDP can do
    whatever blocking-ish async work it needs without ever touching the loop
    that owns the live voice session."""
    bcfg = (config or {}).get("browser", {})
    model = bcfg.get("llm_model", "gemini-2.5-flash")
    fallback_model = bcfg.get("fallback_model", "gemini-2.5-flash-lite")
    max_steps = int(bcfg.get("max_steps", 25))
    result = "(no result)"

    async def _do_run():
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

        _emit_threadsafe(main_loop, runtime.emit("browser", {"id": job_id, "status": "running", "task": task}))
        history = await agent.run(max_steps=max_steps)
        return history

    try:
        history = asyncio.run(_do_run())
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
    _emit_threadsafe(main_loop, runtime.emit("browser", {"id": job_id, "status": "done"}))
    if result == _QUOTA:
        _emit_threadsafe(main_loop, runtime.inject(
            "I couldn't finish browsing — I've hit the free-tier quota on the Gemini API "
            "for web tasks. Tell Ihan: try again later, or add billing / a second API key to lift "
            "the limit. For quick facts I can still read the news instead."
        ))
    else:
        _emit_threadsafe(main_loop, runtime.inject(
            f"The browser finished your task '{task}'. Result: {str(result)[:1200]}"
        ))


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
    # `started` feeds the dashboard's live job list (GET /agents), which sorts
    # by start time and shows how long each worker has been going.
    _jobs[job_id] = {"task": task, "status": "running", "result": None,
                     "started": time.time()}
    main_loop = asyncio.get_running_loop()
    threading.Thread(
        target=_run_browser_thread, args=(job_id, task, ctx.config, main_loop),
        daemon=True, name=f"browser-agent-{job_id}",
    ).start()
    return (f"On it — I've opened a browser and started working on: {task}. "
            "I'll tell you what I find when it's done.")
