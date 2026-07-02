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

_inject_fn = None
_emit_fn = None

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


def set_channels(inject_fn, emit_fn):
    """Called by FreyaModel.run() to publish the active session's channels."""
    global _inject_fn, _emit_fn
    _inject_fn = inject_fn
    _emit_fn = emit_fn


def clear_channels():
    global _inject_fn, _emit_fn
    _inject_fn = None
    _emit_fn = None


def is_live() -> bool:
    return _inject_fn is not None


async def inject(text: str):
    """Make Freya speak `text` out loud now (no-op if no session is live)."""
    if _inject_fn is not None:
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
