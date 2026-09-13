"""
Runtime channels — the bridge that lets *background* powers reach the live session.

Sub-agents, the scheduler, and the ambient watcher all run as independent asyncio
tasks that have no direct handle on the Gemini Live `session`. They still need two
abilities:

  • inject(text)  → make Freya speak something unprompted (proactive speech)
  • emit(evt, p)  → push a status event to the web dashboard

`FreyaModel.run()` registers its own inject/emit functions here on session start and
clears them on stop, so whatever is "live" right now receives the proactive messages.
If nothing is live, calls are silently dropped.
"""

import time
import asyncio

_announcements = set()


def announce(text: str):
    """Best-effort speech, bounded independently of execution and approvals."""
    if _inject_fn is None or len(_announcements) >= 16:
        return
    async def deliver():
        try:
            await asyncio.wait_for(inject(text), 30)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
    task = asyncio.create_task(deliver())
    _announcements.add(task)
    task.add_done_callback(_announcements.discard)

_inject_fn = None
_emit_fn = None

# ── Conversation activity ─────────────────────────────────────────────────
# When the user last said something, and when Freya last answered.
#
# This exists because "idle" meant OS input idle — keyboard and mouse — and
# talking to a voice assistant produces neither. A long spoken session
# therefore looked like an empty chair: the context tracker decided he had been
# away for fifteen minutes, and then "welcomed him back" in the middle of a
# sentence, throwing away the question he had just asked. Speech is presence.
_last_user_turn = 0.0
_last_model_turn = 0.0


def note_user_turn() -> None:
    global _last_user_turn
    _last_user_turn = time.time()


def note_model_turn() -> None:
    global _last_model_turn
    _last_model_turn = time.time()


def seconds_since_activity() -> float:
    """Seconds since either party last spoke. Huge if nothing ever has."""
    latest = max(_last_user_turn, _last_model_turn)
    return 1e9 if latest == 0 else time.time() - latest


def conversation_active(window_s: float = 90.0) -> bool:
    """Is a conversation going on right now?

    Anything proactive must stay out of the way while this is true — an
    interruption doesn't just annoy, it costs the thread of what was being
    discussed.
    """
    return seconds_since_activity() < window_s

# Mic pause state — when True, model.py stops forwarding mic audio to Gemini, so
# ambient sound / a movie can't trigger Freya. Toggled by voice tool, hotkey, or UI.
_paused = False


def is_paused() -> bool:
    return _paused


def set_paused(value: bool):
    global _paused
    _paused = bool(value)
    return _paused


def toggle_paused() -> bool:
    global _paused
    _paused = not _paused
    return _paused


# ── The live transcript ───────────────────────────────────────────────────
# The running record of this session, published the same way the channels are.
#
# The server-side context is not ours to inspect: sliding-window compression can
# evict turns at any moment and tells us nothing when it does. This collector is
# the one copy of the conversation we fully control, so it is what `recall_
# conversation` reads when a back-reference ("question 12", "that file") no
# longer means anything to her.
_transcript = None


def set_transcript(collector):
    global _transcript
    _transcript = collector


def get_transcript():
    """The live TranscriptCollector, or None if no session is running."""
    return _transcript


def set_channels(inject_fn, emit_fn):
    """Called by FreyaModel.run() to publish the active session's channels."""
    global _inject_fn, _emit_fn
    _inject_fn = inject_fn
    _emit_fn = emit_fn


def clear_channels():
    global _inject_fn, _emit_fn, _transcript
    _inject_fn = None
    _emit_fn = None
    _transcript = None
    for task in tuple(_announcements):
        task.cancel()


def is_live() -> bool:
    return _inject_fn is not None


async def inject(text: str, priority: str = "normal"):
    """Make Freya speak `text` out loud now (no-op if no session is live).

    `priority` decides what happens when the user is mid-conversation:

      "low"     Ambient nudges and context suggestions. Dropped outright — the
                moment for "welcome back" is gone once he's already talking, and
                delivering it late is worse than not at all: it derails whatever
                he actually asked about.
      "normal"  Results he's waiting on — a finished sub-agent, an approval
                outcome, a mission report. Held until there's a gap, never
                dropped, because he asked for these.
    """
    if _inject_fn is None:
        # Worth saying out loud: this is the reason a webcam gesture touch or a
        # finished sub-agent can appear to do nothing at all. Freya only speaks
        # while a voice session is running — press START on the dashboard.
        print(f"  [runtime] no live session — dropped proactive line: {text[:80]}")
        return

    if priority == "low" and conversation_active():
        print(f"  [runtime] mid-conversation — dropped nudge: {text[:70]}")
        return

    try:
        await _inject_fn(text)
    except Exception as e:
        print(f"  [runtime] inject failed: {e}")


async def emit(event_type: str, payload: dict):
    """Broadcast a status event to the dashboard.

    Transport is the session-independent event bus (core/events.py): server.py
    subscribes its WebSocket broadcaster once at startup, so mission progress,
    approval requests and suggestions reach the UI even when no voice session
    is live. `_emit_fn` is intentionally NOT called here anymore — it caused
    every event to be delivered twice once the bus existed.
    """
    from core.events import bus
    await bus.publish(event_type, payload)
