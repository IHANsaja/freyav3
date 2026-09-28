"""
Recovery protocol — the rules every layer follows so one failure never stops Freya.

The voice loop already survived most single faults (a failing tool, a rotated
session, an overloaded model). What it lacked was a *protocol*: a shared answer to
"what happens next" for the failures that remained terminal —

  * five reconnects in a row and the session gave up for good;
  * a refused API key stopped the session, and fixing the key did nothing until
    someone pressed Start again;
  * a crash outside the reconnect loop (opening the mic, building the prompt)
    ended the session with nothing on screen;
  * a tool that hung never returned, and every call queued behind it waited forever;
  * a tool that failed every time was retried every time.

The protocol, in order of escalation:

  1. **Contain** — every step runs guarded (`guard` / `aguard`): a failure is
     logged with its traceback and replaced by a fallback value, never raised
     into the loop that called it.
  2. **Degrade** — when a part can't work (a saved audio device vanished, the
     memory store is locked, a tool keeps failing), use the next-best thing
     (the default device, the base personality, "that tool is resting — use
     another way") and say so on the dashboard.
  3. **Retry forever, politely** — while the user wants a session, reconnect
     with capped, jittered exponential backoff (`Backoff`). There is no "max
     attempts": the cap only slows retries down.
  4. **Report** — every component's state lives in `health`, published as a
     `health` event and replayed to reconnecting dashboards, so the UI always
     knows whether she is fine, degraded, recovering or down — and why.

Nothing here imports the rest of Freya at module load, so any layer can use it.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.errors import log_error

# Health states, mildest first. The overall state is the worst component's.
OK, DEGRADED, RECOVERING, DOWN = "ok", "degraded", "recovering", "down"
_SEVERITY = {OK: 0, DEGRADED: 1, RECOVERING: 2, DOWN: 3}


# ══════════════════════════════════════════════
#  1. CONTAIN
# ══════════════════════════════════════════════
def guard(where: str, fn: Callable[..., Any], *args, fallback: Any = None,
          level: int = logging.WARNING, **kwargs) -> Any:
    """Call `fn(*args, **kwargs)`; on any exception log it and return `fallback`."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        log_error(where, exc, level=level)
        return fallback


async def aguard(where: str, awaitable: Awaitable[Any], *, fallback: Any = None,
                 timeout: float | None = None, level: int = logging.WARNING) -> Any:
    """Await `awaitable` (optionally bounded by `timeout`); on failure return `fallback`.

    Cancellation is never swallowed — a stopped session must still stop.
    """
    try:
        if timeout is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_error(where, exc, level=level)
        return fallback


# ══════════════════════════════════════════════
#  3. RETRY FOREVER, POLITELY
# ══════════════════════════════════════════════
class Backoff:
    """Capped exponential backoff with jitter: base, 2·base, 4·base … ≤ cap.

    Jitter (±20%) keeps two things that failed together (the voice session and a
    dashboard reconnect, say) from retrying in lock-step forever.
    """

    def __init__(self, base: float = 1.0, cap: float = 30.0, jitter: float = 0.2):
        self.base, self.cap, self.jitter = base, cap, jitter
        self.attempt = 0

    def next(self) -> float:
        delay = min(self.cap, self.base * (2 ** self.attempt))
        self.attempt += 1
        return max(0.0, delay * (1 + random.uniform(-self.jitter, self.jitter)))

    def reset(self) -> None:
        self.attempt = 0


# ══════════════════════════════════════════════
#  2. DEGRADE — tool circuit breaker
# ══════════════════════════════════════════════
class ToolBreaker:
    """Stops re-running a tool that keeps failing, for a short rest.

    After `threshold` consecutive failures (exceptions or timeouts, not a tool
    that *answered* with bad news) the tool is "open" for `rest_s`: calls are
    answered at once with a message telling her to use another route. One
    success closes it again. Without this, a broken tool (a missing binary, a
    dead MCP server) was retried on every request, each time costing the full
    timeout while she sat silent.
    """

    def __init__(self, threshold: int = 3, rest_s: float = 90.0):
        self.threshold, self.rest_s = threshold, rest_s
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, name: str) -> bool:
        until = self._open_until.get(name)
        if until is None:
            return False
        if time.monotonic() >= until:
            # Half-open: allow one attempt; a failure re-opens immediately.
            self._open_until.pop(name, None)
            self._failures[name] = self.threshold - 1
            return False
        return True

    def rest_left(self, name: str) -> float:
        return max(0.0, self._open_until.get(name, 0.0) - time.monotonic())

    def success(self, name: str) -> None:
        self._failures.pop(name, None)
        self._open_until.pop(name, None)

    def failure(self, name: str) -> bool:
        """Record a failure; True when this one tripped the breaker open."""
        n = self._failures.get(name, 0) + 1
        self._failures[name] = n
        if n >= self.threshold:
            self._open_until[name] = time.monotonic() + self.rest_s
            return True
        return False

    def open_tools(self) -> list[str]:
        return [n for n in list(self._open_until) if self.is_open(n)]

    def resting_message(self, name: str) -> str:
        return (f"{name} is resting after failing {self.threshold} times in a row "
                f"(back in ~{int(self.rest_left(name)) + 1}s). Don't call it again now: "
                "reach the goal another way (a different tool, run_tool with an "
                "alternative, or ask the user), and tell him briefly what you're doing.")


breaker = ToolBreaker()


# ══════════════════════════════════════════════
#  4. REPORT — component health
# ══════════════════════════════════════════════
@dataclass
class Component:
    state: str = OK
    detail: str = ""
    since: float = field(default_factory=time.time)
    failures: int = 0

    def to_payload(self, name: str) -> dict:
        return {"name": name, "state": self.state, "detail": self.detail,
                "since": self.since, "failures": self.failures}


class Health:
    """Per-component health, published to the dashboard on every change."""

    COMPONENTS = ("live", "mic", "speaker", "memory", "tools")

    def __init__(self):
        self._parts: dict[str, Component] = {name: Component() for name in self.COMPONENTS}

    def set(self, name: str, state: str, detail: str = "") -> None:
        part = self._parts.setdefault(name, Component())
        changed = part.state != state or part.detail != detail
        if part.state != state:
            part.since = time.time()
        part.failures = 0 if state == OK else part.failures + 1
        part.state, part.detail = state, detail
        if changed:
            self._publish()

    def ok(self, name: str) -> None:
        self.set(name, OK, "")

    def get(self, name: str) -> Component:
        return self._parts.setdefault(name, Component())

    def overall(self) -> str:
        worst = max(self._parts.values(), key=lambda c: _SEVERITY.get(c.state, 0))
        return worst.state

    def snapshot(self) -> dict:
        return {
            "overall": self.overall(),
            "components": [c.to_payload(n) for n, c in self._parts.items()],
            "resting_tools": breaker.open_tools(),
            "ts": time.time(),
        }

    def reset(self) -> None:
        for part in self._parts.values():
            part.state, part.detail, part.failures = OK, "", 0
        self._publish()

    def _publish(self) -> None:
        # publish_soon works from any thread and any loop; before the server's
        # loop exists (tests, main.py) there is simply no one to tell.
        try:
            from core.events import bus
            bus.publish_soon("health", self.snapshot())
        except Exception as exc:
            log_error("resilience.health.publish", exc, level=logging.DEBUG)


health = Health()
