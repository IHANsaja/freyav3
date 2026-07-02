"""
Typed event bus — the session-independent transport behind `runtime.emit()`.

Why this exists
---------------
`runtime.emit()` used to forward events through a callback the live Gemini session
registered on start and cleared on stop. That meant mission progress, approval
requests, and proactive suggestions silently vanished whenever no voice session was
running — exactly the moments a background mission is most likely to need the UI.

The bus is subscribed once by `server.py` at process startup, so events always reach
connected dashboard clients. It also keeps a short replay buffer so a client that
(re)connects mid-mission can catch up instead of showing stale state.

Serialization contract
----------------------
New event families (`NEW_TYPES`) go over the wire as `{"type": t, "payload": {...}}`.
Legacy families (agent, browser, schedule, ambient, mcp, news, ...) keep their original
flat shape `{"type": t, **payload}` so existing frontend handlers don't break.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

# Families introduced with the mission/approval/avatar upgrade — nested payload shape.
NEW_TYPES = {
    "mission", "approval", "avatar", "suggestion", "context", "persona", "memory_changed",
}

# Only these families are replayed to newly connected clients. Transient audio-ish
# events (speech, state, image) would be confusing or heavy to replay.
REPLAYABLE = NEW_TYPES | {"agent", "browser", "schedule", "ambient", "mcp"}


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict
    ts: float = field(default_factory=time.time)

    def serialize(self) -> dict:
        """Wire format — see module docstring for the legacy/new split."""
        if self.type in NEW_TYPES:
            return {"type": self.type, "payload": self.payload}
        return {"type": self.type, **(self.payload or {})}


class EventBus:
    def __init__(self, buffer_size: int = 50):
        self._subscribers: list[Callable[[Event], Awaitable[None]]] = []
        self._buffer: list[Event] = []
        self._buffer_size = buffer_size

    def subscribe(self, fn: Callable[[Event], Awaitable[None]]) -> Callable[[], None]:
        """Register an async listener. Returns an unsubscribe function."""
        self._subscribers.append(fn)

        def unsubscribe():
            try:
                self._subscribers.remove(fn)
            except ValueError:
                pass

        return unsubscribe

    async def publish(self, event_type: str, payload: dict):
        event = Event(type=event_type, payload=payload or {})
        if event.type in REPLAYABLE:
            self._buffer.append(event)
            if len(self._buffer) > self._buffer_size:
                self._buffer = self._buffer[-self._buffer_size:]
        # Isolate subscribers: one broken listener must not starve the others.
        for fn in list(self._subscribers):
            try:
                await fn(event)
            except Exception as e:
                print(f"  [events] subscriber failed on '{event.type}': {e}")

    def publish_soon(self, event_type: str, payload: dict):
        """Fire-and-forget publish from sync code that runs inside the loop."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event_type, payload))
        except RuntimeError:
            pass  # no loop — nothing is listening anyway

    def replay_buffer(self, n: int = 50) -> list[Event]:
        return self._buffer[-n:]


bus = EventBus()
