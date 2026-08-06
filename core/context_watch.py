"""
Always-on context awareness — cheap, metadata-only, respectful.

Unlike core/ambient.py's explicit `watch_screen` (vision model on a screenshot loop),
this tracker never captures the screen on its own. It polls only Win32 metadata —
foreground window title, owning process, seconds since last input — every few seconds,
keeps a rolling activity log, and fires *suggestions* from pure heuristics:

  stuck        — same window focused ≥ N minutes with active input
  idle_return  — input resumes after a long idle gap
  form_like    — the focused window title matches form/checkout patterns
  followup_due — handled by the scheduler via the memory store

On a trigger it makes ONE cheap text-model call to phrase a one-line suggestion,
published as a `suggestion` event (dashboard chip). Voice only if configured.
Vision happens only if the user *accepts* a suggestion. Rate limits: per-kind
cooldowns that back off 2x each time a suggestion is dismissed, a global hourly
cap, quiet hours, and a hard mute while listening is paused.

Opt-in: config `ambient.context_tracker.enabled` (default false).
"""

import asyncio
import itertools
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from core import runtime
from core.registry import tool, OBJ, P, STR

_POLL_S = 3.0
_DEBOUNCE_S = 5.0
_GLOBAL_CAP_PER_HOUR = 4

_FORM_PATTERNS = re.compile(
    r"\b(checkout|sign\s*up|register|application|apply|form|questionnaire|survey|booking)\b",
    re.IGNORECASE,
)

_counter = itertools.count(1)


def _win_snapshot() -> tuple[str, str, float]:
    """(process_name, window_title, idle_seconds) — pywin32/psutil only."""
    import win32api
    import win32gui
    import win32process
    import psutil

    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd) or ""
    app = ""
    try:
        _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = psutil.Process(pid).name()
    except Exception:
        pass
    idle_ms = win32api.GetTickCount() - win32api.GetLastInputInfo()
    return app, title, max(0.0, idle_ms / 1000.0)


@dataclass
class _Span:
    app: str
    title: str
    started: float


class ContextTracker:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._config: dict = {}
        self._history: deque[_Span] = deque(maxlen=100)
        self._current: _Span | None = None
        self._last_emit = 0.0
        self._last_idle_s = 0.0
        self._cooldowns: dict[str, float] = {}   # kind -> next allowed ts
        self._cooldown_len: dict[str, float] = {}  # kind -> current cooldown seconds
        self._fired_this_hour: deque[float] = deque(maxlen=_GLOBAL_CAP_PER_HOUR)
        self._suggestions: dict[str, dict] = {}
        self._stuck_fired_for: str = ""

    # ── Lifecycle (mirrors Scheduler.attach/detach) ────────────────────────

    def _cfg(self) -> dict:
        return ((self._config or {}).get("ambient", {}) or {}).get("context_tracker", {}) or {}

    def enabled(self) -> bool:
        return bool(self._cfg().get("enabled", False))

    def attach(self, config: dict):
        self._config = config
        if not self.enabled():
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())
        print("  [context] tracker attached.")

    def detach(self):
        if self._task:
            self._task.cancel()
            self._task = None

    def set_enabled(self, value: bool):
        self._config.setdefault("ambient", {}).setdefault("context_tracker", {})["enabled"] = value
        if value:
            self.attach(self._config)
        else:
            self.detach()

    # ── Main loop ──────────────────────────────────────────────────────────

    async def _loop(self):
        loop = asyncio.get_running_loop()
        try:
            while True:
                await asyncio.sleep(_POLL_S)
                if runtime.is_paused():
                    continue
                try:
                    app, title, idle_s = await loop.run_in_executor(None, _win_snapshot)
                except Exception:
                    continue
                await self._observe(app, title, idle_s)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [context] loop error: {e}")

    async def _observe(self, app: str, title: str, idle_s: float):
        now = time.time()

        # `idle_s` is OS input idle — keyboard and mouse only. A voice
        # conversation moves neither, so an hour of talking looked identical to
        # an hour of nobody being there, and the idle_return nudge fired at the
        # worst possible moment. If he has spoken more recently than he has
        # typed, that is how long he has actually been idle.
        idle_s = min(idle_s, runtime.seconds_since_activity())

        changed = (self._current is None or self._current.app != app
                   or self._current.title != title)
        if changed:
            if self._current:
                self._history.append(self._current)
                # A finished span is the raw material of the day context: where
                # the hours actually went, and what was open long enough to
                # count as "what he was working on".
                self._record_span(self._current, now)
            self._current = _Span(app=app, title=title, started=now)
            self._stuck_fired_for = ""
            if now - self._last_emit > _DEBOUNCE_S:
                self._last_emit = now
                await runtime.emit("context", {"app": app, "title": title[:120],
                                               "idleS": int(idle_s)})

        # idle_return: long gap just ended
        idle_return_min = float(self._cfg().get("idle_return_minutes", 15))
        if self._last_idle_s >= idle_return_min * 60 and idle_s < 5:
            await self._trigger("idle_return",
                                f"the user just came back after {int(self._last_idle_s / 60)} minutes away. "
                                f"He was last on '{title}' in {app}.")
        self._last_idle_s = idle_s

        if self._current and idle_s < 60:
            span_key = f"{self._current.app}|{self._current.title}"
            stuck_min = float(self._cfg().get("stuck_minutes", 10))
            if (now - self._current.started >= stuck_min * 60
                    and self._stuck_fired_for != span_key):
                self._stuck_fired_for = span_key
                await self._trigger("stuck",
                                    f"the user has been on the same window for {int(stuck_min)}+ minutes "
                                    f"with active input: '{title}' in {app}. He might be stuck or deep in focus.")
            if changed and _FORM_PATTERNS.search(title):
                await self._trigger("form",
                                    f"the user just opened what looks like a form: '{title}' in {app}.")

    _FOCUS_WORTH_NOTING_S = 8 * 60

    def _record_span(self, span: _Span, ended: float):
        """Feed a finished focus span into the day context (never raises)."""
        duration = ended - span.started
        try:
            from core import day_context
            day_context.note_activity(span.app, span.title, duration)
            # Only long, deliberate stretches earn a line in the day's timeline —
            # a timeline of every alt-tab is noise, not context.
            if duration >= self._FOCUS_WORTH_NOTING_S and span.title:
                minutes = int(duration // 60)
                day_context.note("focus", f"{minutes}m on '{span.title[:100]}' ({span.app})",
                                 subject=span.app)
        except Exception:
            pass

    # ── Suggestion pipeline ────────────────────────────────────────────────

    def _in_quiet_hours(self) -> bool:
        hours = self._cfg().get("quiet_hours") or []
        if len(hours) != 2:
            return False
        now = datetime.now().strftime("%H:%M")
        start, end = hours
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end  # crosses midnight

    def _rate_ok(self, kind: str) -> bool:
        now = time.time()
        if self._in_quiet_hours():
            return False
        if now < self._cooldowns.get(kind, 0):
            return False
        if len(self._fired_this_hour) == _GLOBAL_CAP_PER_HOUR and \
                now - self._fired_this_hour[0] < 3600:
            return False
        return True

    async def _trigger(self, kind: str, situation: str):
        if not self._rate_ok(kind):
            return
        base = float(self._cfg().get("cooldown_minutes", 30)) * 60
        self._cooldown_len.setdefault(kind, base)
        self._cooldowns[kind] = time.time() + self._cooldown_len[kind]
        self._fired_this_hour.append(time.time())

        text = await self._draft(kind, situation)
        if not text:
            return
        sid = f"s-{next(_counter)}"
        self._suggestions[sid] = {"kind": kind, "text": text, "situation": situation}
        await runtime.emit("suggestion", {"event": "created", "id": sid,
                                          "text": text, "kind": kind})
        if self._cfg().get("voice_suggestions", False):
            # Low priority: if he's already talking to her, this nudge is stale
            # and gets dropped. The dashboard suggestion above still stands, so
            # nothing is lost — it just doesn't hijack a live conversation.
            await runtime.inject(
                f"[Proactive nudge, keep it to one casual sentence]: {text}", priority="low")

    async def _draft(self, kind: str, situation: str) -> str:
        """One cheap text call to phrase the suggestion. No screenshots."""
        try:
            from google import genai
            from config import get_agent_api_key
            client = genai.Client(api_key=get_agent_api_key())
            resp = await client.aio.models.generate_content(
                model=self._cfg().get("draft_model", "gemini-2.5-flash-lite"),
                contents=(
                    "You are Freya, a proactive assistant. Based on this observation, write ONE "
                    "short, casual, genuinely useful suggestion to the user (max 15 words). Offer help, "
                    "don't nag. No emoji, no preamble.\n"
                    f"OBSERVATION ({kind}): {situation}"
                ),
            )
            return (resp.text or "").strip().strip('"')[:160]
        except Exception:
            # Model unavailable → canned fallbacks keep the feature working.
            canned = {
                "stuck": "You've been on this a while — want me to take a look?",
                "form": "That looks like a form — want me to help fill it?",
                "idle_return": "Welcome back. Want a quick recap of where you left off?",
            }
            return canned.get(kind, "")

    async def respond(self, suggestion_id: str, accepted: bool):
        """UI accept/dismiss. Dismissal doubles that kind's cooldown (it learns)."""
        entry = self._suggestions.pop(suggestion_id, None)
        if entry is None:
            return
        kind = entry["kind"]
        await runtime.emit("suggestion", {"event": "resolved", "id": suggestion_id,
                                          "text": entry["text"], "kind": kind})
        if accepted:
            base = float(self._cfg().get("cooldown_minutes", 30)) * 60
            self._cooldown_len[kind] = base  # reset backoff — it was welcome
            await runtime.inject(
                f"[the user accepted your suggestion: '{entry['text']}' (context: {entry['situation']}). "
                f"Act on it now — look at the screen with capture_screen if needed.]"
            )
        else:
            self._cooldown_len[kind] = min(self._cooldown_len.get(kind, 1800) * 2, 8 * 3600)


tracker = ContextTracker()


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "enable_context_awareness",
    "Turn on always-on context awareness: Freya quietly tracks the active window and "
    "offers occasional proactive suggestions (never screenshots without asking).",
)
async def enable_context_awareness(args, ctx) -> str:
    tracker._config = ctx.config
    tracker.set_enabled(True)
    return "Context awareness is on. I'll keep an eye out and nudge you sparingly."


@tool(
    "disable_context_awareness",
    "Turn off always-on context awareness and its proactive suggestions.",
)
async def disable_context_awareness(args, ctx) -> str:
    tracker.set_enabled(False)
    return "Context awareness is off."
