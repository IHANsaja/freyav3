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

from config import get_api_key
from core import runtime
from core.registry import tool, OBJ, P, STR

_counter = itertools.count(1)
_jobs: dict[str, dict] = {}


async def _run_browser(job_id: str, task: str, config: dict):
    bcfg = (config or {}).get("browser", {})
    model = bcfg.get("llm_model", "gemini-2.5-flash")
    max_steps = int(bcfg.get("max_steps", 25))
    result = "(no result)"
    try:
        from browser_use import Agent, ChatGoogle
        key = get_api_key()
        os.environ.setdefault("GOOGLE_API_KEY", key)
        try:
            llm = ChatGoogle(model=model, api_key=key)
        except TypeError:
            llm = ChatGoogle(model=model)  # older signature reads env
        agent = Agent(task=task, llm=llm)
        await runtime.emit("browser", {"id": job_id, "status": "running", "task": task})
        history = await agent.run(max_steps=max_steps)
        # browser-use returns an AgentHistoryList; extract the final answer robustly.
        try:
            result = history.final_result() or str(history)
        except Exception:
            result = str(history)
    except Exception as e:
        result = f"The browser agent hit an error: {e}"

    _jobs[job_id].update(status="done", result=result)
    await runtime.emit("browser", {"id": job_id, "status": "done"})
    await runtime.inject(
        f"The browser finished your task '{task}'. Result: {str(result)[:1200]}"
    )


@tool(
    "browser_task",
    "Your ONLY web browser tool. Use it for ANY request that involves the internet: search the web, "
    "google something, look something up, play/find a YouTube video, search documentation, find a "
    "StackOverflow answer or debug an error online, browse a site, research, fill a form, or "
    "compare/check info. It autonomously drives a real Chromium browser, runs in the background, "
    "and reports back out loud when done. Tell Ihan you've started it.",
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
