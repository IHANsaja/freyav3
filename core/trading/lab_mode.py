"""
Lab presence → Trading Teacher mode.

While the Trading Lab is open in front of him during a voice session, Freya
becomes his trading teacher (config/teacher.py); when he leaves the lab she
goes back to whichever mode she was in before. The switch goes through the
live session's own mode-change path (runtime.request_mode), so the
conversation carries across.

Rules, so it never fights him:
  * only while a voice session is live, and only if `trading.teacher_mode`
    is on (default);
  * he picked another mode himself while the lab was open → leave it alone
    until the lab closes;
  * she only switches back if it was the lab that switched her, and only
    after a grace period (a reload or a quick alt-tab isn't "leaving");
  * modes with their own model or purpose are never overridden
    (`KEEP_MODES` — e.g. mid-way through a complex task).

The page reports itself every 20 s and on focus/visibility changes
(POST /trading/workspace), which is what drives `on_workspace`.
"""

from __future__ import annotations

import asyncio
import time

from config.teacher import MODE_ID as TEACHER

RETURN_GRACE_S = 25.0
SWITCH_PENDING_S = 30.0      # a requested switch waits for a pause before it lands
VIEW_FRESH_S = 60.0          # a view not refreshed for this long doesn't count
KEEP_MODES = {"complex_tasks", "night_guardian"}


class LabPresence:
    def __init__(self):
        self.return_to: str | None = None    # set only when WE switched her
        self.opted_out = False               # he chose another mode inside the lab
        self._requested_at = 0.0             # when we last asked for the teacher
        self._return_task: asyncio.Task | None = None
        self._greet_task: asyncio.Task | None = None

    # ── inputs ──
    def lab_in_use(self) -> bool:
        from core.trading.guide import _views, _lock
        now = time.monotonic()
        with _lock:
            return any(v.get("active") and now - v.get("updated", 0) < VIEW_FRESH_S for v in _views.values())

    async def on_workspace(self, service=None, body=None) -> None:
        """Called after every workspace sync from the Trading Lab page."""
        from config import load_config
        from core import runtime
        config = load_config()
        if not (config.get("trading") or {}).get("teacher_mode", True):
            return
        mode = config.get("active_mode", "default")

        if self.lab_in_use():
            self._cancel_return()
            if not runtime.is_live():
                return
            pending = time.monotonic() - self._requested_at < SWITCH_PENDING_S
            if self.return_to is not None and mode != TEACHER and not pending:
                # We switched her, and now she's in something else: his choice.
                self.opted_out = True
                self.return_to = None
            if pending and mode != TEACHER:
                return                       # our request hasn't landed yet
            if self.opted_out or mode == TEACHER or mode in KEEP_MODES:
                return
            if TEACHER not in (config.get("modes") or {}):
                return
            if await runtime.request_mode(TEACHER, "trading_lab"):
                self._requested_at = time.monotonic()
                self.return_to = mode
                self._schedule_greeting(service, body)
        else:
            self.opted_out = False
            if self.return_to is not None and self._return_task is None:
                self._return_task = asyncio.create_task(self._return_after_grace())

    # ── switching back ──
    async def _return_after_grace(self):
        try:
            await asyncio.sleep(RETURN_GRACE_S)
            if self.lab_in_use():
                return
            from config import load_config
            from core import runtime
            target, self.return_to = self.return_to, None
            if target and load_config().get("active_mode") == TEACHER:
                await runtime.request_mode(target, "left_trading_lab")
        finally:
            self._return_task = None

    def _cancel_return(self):
        if self._return_task is not None:
            self._return_task.cancel()
            self._return_task = None

    # ── arriving ──
    def _schedule_greeting(self, service, body):
        """Once the teacher session is live, give her the lab's facts so her
        first line can be about what he's actually looking at."""
        if service is None or body is None or self._greet_task is not None:
            return

        async def greet():
            from config import load_config
            from core import runtime
            from core.trading.guide import voice_briefing
            try:
                # The reconnect takes a few seconds; wait for the new session.
                await asyncio.sleep(2)
                for _ in range(60):
                    if runtime.is_live() and load_config().get("active_mode") == TEACHER:
                        break
                    await asyncio.sleep(0.5)
                else:
                    return
                note = voice_briefing(service, body)
                if note:
                    await runtime.inject(note)
            except Exception as exc:
                print(f"  [trading] teacher greeting skipped: {exc}")
            finally:
                self._greet_task = None

        self._greet_task = asyncio.create_task(greet())


presence = LabPresence()
