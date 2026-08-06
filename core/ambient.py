"""
Proactive ambient awareness — Freya watches and speaks up on her own.

Two abilities that make her feel present rather than purely reactive:

  • watch_screen(instruction): a background loop periodically captures the screen and asks a
    cheap Gemini vision model "has <condition> happened?". The moment it has, Freya proactively
    says so (runtime.inject) and stops watching — e.g. "tell me when my build finishes" or
    "let me know when the download is done".
  • Optional wake-word (pvporcupine) for hands-free "Hey Freya" activation if the package is
    present. Absent by default → simply unavailable, no crash.

Gated behind config `ambient.enabled`.
"""

import asyncio
import itertools

from config import get_agent_api_key
from core import runtime
from core.registry import tool, OBJ, P, STR, INT

_counter = itertools.count(1)


class Ambient:
    def __init__(self):
        self._watchers: dict[str, asyncio.Task] = {}

    def stop_all(self):
        for t in self._watchers.values():
            t.cancel()
        self._watchers.clear()

    def start_watch(self, config, instruction, interval, max_minutes):
        wid = f"watch-{next(_counter)}"
        self._watchers[wid] = asyncio.create_task(
            self._watch(wid, config, instruction, interval, max_minutes))
        return wid

    async def _watch(self, wid, config, instruction, interval, max_minutes):
        from google import genai
        from google.genai import types
        model = (config or {}).get("ambient", {}).get("vision_model", "gemini-2.5-flash")
        client = genai.Client(api_key=get_agent_api_key())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_minutes * 60
        try:
            while loop.time() < deadline:
                await asyncio.sleep(interval)
                from core.vision import capture_screen
                import base64
                b64 = await loop.run_in_executor(None, capture_screen)
                prompt = (
                    f"You are monitoring a screen for this condition: '{instruction}'. "
                    "Answer strictly 'YES: <one short reason>' if the condition is now true, "
                    "otherwise answer exactly 'NO'."
                )
                resp = await client.aio.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=[
                        types.Part(text=prompt),
                        types.Part(inline_data=types.Blob(
                            data=base64.b64decode(b64), mime_type="image/jpeg")),
                    ])],
                )
                answer = (resp.text or "").strip()
                if answer.upper().startswith("YES"):
                    note = answer.split(":", 1)[1].strip() if ":" in answer else ""
                    await runtime.inject(
                        f"Heads up — the thing you asked me to watch for just happened: "
                        f"{instruction}. {note}")
                    await runtime.emit("ambient", {"id": wid, "status": "triggered"})
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [ambient] watcher error: {e}")
        finally:
            self._watchers.pop(wid, None)


ambient = Ambient()


@tool(
    "watch_screen",
    "Proactively monitor the screen and tell the user the moment a condition becomes true, without "
    "him asking again. Use for 'tell me when X finishes/appears/changes'. Runs in the background.",
    OBJ({"instruction": P(STR, "The condition to watch for, e.g. 'the video export reaches 100%'"),
         "interval_seconds": P(INT, "How often to check (default 20)"),
         "max_minutes": P(INT, "Give up after this many minutes (default 30)")}, ["instruction"]),
    gate="ambient.enabled",
)
async def watch_screen(args, ctx) -> str:
    # MUST be async: start_watch() schedules a background task with
    # asyncio.create_task, which requires the running session loop. (A sync
    # handler would run in an executor thread with no loop → "no running event loop".)
    instruction = (args.get("instruction") or "").strip()
    if not instruction:
        return "What should I watch for?"
    interval = max(5, int(args.get("interval_seconds", 20) or 20))
    max_minutes = max(1, int(args.get("max_minutes", 30) or 30))
    wid = ambient.start_watch(ctx.config, instruction, interval, max_minutes)
    return (f"Watching your screen for: {instruction}. I'll speak up the moment it happens "
            f"(checking every {interval}s for up to {max_minutes} min). [{wid}]")


@tool("stop_watching", "Stop all active proactive screen-watchers.", OBJ(),
      gate="ambient.enabled")
async def stop_watching(args, ctx) -> str:
    # Async so task.cancel() runs on the loop thread, not an executor thread.
    ambient.stop_all()
    return "Stopped watching the screen."
