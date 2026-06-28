"""
Persistent scheduler & daily briefings.

The old `set_reminder` (core/tools.py) spawned a throwaway thread that popped a Windows
message box — it died with the process and Freya never *said* anything. This replaces it with
a real scheduler:

  • Jobs persist to memory/schedule.json and survive restarts.
  • A background loop (bound to the live session via `attach`) checks due jobs every 15s and
    makes Freya SPEAK them through the proactive channel (runtime.inject).
  • Supports one-shot ("in 10 minutes") and daily ("every day at 08:00") jobs.
  • Special action `morning_briefing` assembles news + weather and delivers it out loud.

Gated behind config `scheduler.enabled` (defaults on).
"""

import asyncio
import json
import os
import time
from datetime import datetime

from core import runtime
from core.registry import tool, OBJ, P, STR, INT

_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "schedule.json")


def _load() -> list[dict]:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(jobs: list[dict]):
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
    except Exception as e:
        print(f"  [scheduler] save failed: {e}")


class Scheduler:
    def __init__(self):
        self._task = None
        self._config = None

    def attach(self, config: dict):
        """Start the background loop for the current live session."""
        self._config = config
        if not (config or {}).get("scheduler", {}).get("enabled", True):
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    def detach(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        try:
            while True:
                await asyncio.sleep(15)
                await self._tick()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [scheduler] loop error: {e}")

    async def _tick(self):
        jobs = _load()
        now = time.time()
        now_hhmm = datetime.now().strftime("%H:%M")
        today = datetime.now().strftime("%Y-%m-%d")
        changed = False
        for job in jobs:
            fire = False
            if job.get("kind") == "once" and now >= job.get("due_ts", 0) and not job.get("fired"):
                fire = True
                job["fired"] = True
                changed = True
            elif job.get("kind") == "daily" and job.get("at") == now_hhmm and job.get("last") != today:
                fire = True
                job["last"] = today
                changed = True
            if fire:
                await self._fire(job)
        # Drop spent one-shots.
        kept = [j for j in jobs if not (j.get("kind") == "once" and j.get("fired"))]
        if changed or len(kept) != len(jobs):
            _save(kept)

    async def _fire(self, job: dict):
        action = job.get("action", "")
        if action == "morning_briefing":
            await runtime.inject(await self._briefing())
        else:
            await runtime.inject(f"Scheduled reminder for Ihan: {action}")
        await runtime.emit("schedule", {"id": job.get("id"), "status": "fired", "action": action})

    async def _briefing(self) -> str:
        parts = ["Good morning Ihan, here's your briefing."]
        loop = asyncio.get_running_loop()
        try:
            from core.news import _fetch_headlines, _TOP
            heads = await loop.run_in_executor(None, _fetch_headlines, _TOP, 3)
            if heads:
                parts.append("Top news: " + "; ".join(heads) + ".")
        except Exception:
            pass
        try:
            city = (self._config or {}).get("scheduler", {}).get("briefing_city")
            if city:
                from core.tools import get_weather
                parts.append(await loop.run_in_executor(None, get_weather, city))
        except Exception:
            pass
        return " ".join(parts)


scheduler = Scheduler()


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "schedule_task",
    "Schedule something for the future that Freya will SAY out loud when due. Use for reminders "
    "and recurring briefings. Provide either minutes_from_now (one-shot) or daily_time HH:MM "
    "(every day).",
    OBJ({"action": P(STR, "What to remind/do, e.g. 'tell Ihan to join the standup' or "
                          "'morning_briefing'"),
         "minutes_from_now": P(INT, "Fire once after this many minutes"),
         "daily_time": P(STR, "Fire every day at this 24h time, e.g. 08:30")}, ["action"]),
)
def schedule_task(args, ctx) -> str:
    action = (args.get("action") or "").strip()
    if not action:
        return "What should I schedule?"
    jobs = _load()
    jid = f"job-{int(time.time())}"
    if args.get("daily_time"):
        jobs.append({"id": jid, "kind": "daily", "at": str(args["daily_time"]), "action": action})
        _save(jobs)
        return f"Scheduled '{action}' every day at {args['daily_time']}."
    minutes = int(args.get("minutes_from_now", 0) or 0)
    if minutes <= 0:
        return "Give me minutes_from_now or a daily_time."
    jobs.append({"id": jid, "kind": "once", "due_ts": time.time() + minutes * 60, "action": action})
    _save(jobs)
    return f"Got it — I'll remind you in {minutes} minute{'s' if minutes != 1 else ''}: {action}"


@tool("list_tasks", "List all scheduled reminders and recurring tasks.", OBJ())
def list_tasks(args, ctx) -> str:
    jobs = _load()
    if not jobs:
        return "You have no scheduled tasks."
    out = []
    for j in jobs:
        if j.get("kind") == "daily":
            out.append(f"{j['id']}: daily at {j.get('at')} — {j.get('action')}")
        else:
            mins = max(0, int((j.get("due_ts", 0) - time.time()) / 60))
            out.append(f"{j['id']}: in ~{mins} min — {j.get('action')}")
    return "Scheduled: " + "; ".join(out)


@tool("cancel_task", "Cancel a scheduled task by its id.",
      OBJ({"id": P(STR, "The job id from list_tasks")}, ["id"]))
def cancel_task(args, ctx) -> str:
    jid = args.get("id", "")
    jobs = _load()
    kept = [j for j in jobs if j.get("id") != jid]
    if len(kept) == len(jobs):
        return f"No task with id {jid}."
    _save(kept)
    return f"Cancelled {jid}."
