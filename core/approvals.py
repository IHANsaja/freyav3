"""
Approval gate — human-in-the-loop checkpoint for sensitive or irreversible actions.

Two execution paths, because the Gemini Live receive loop must never block:

  • LIVE path (voice session tool call): the tool returns immediately with an
    APPROVAL_REQUIRED token instructing Freya to explain the action and ask out loud.
    The real work is captured in a deferred `thunk` that runs only when the user
    approves — by saying yes (Gemini calls `approve_action`) or clicking the
    dashboard's Approve button.

  • MISSION path (background orchestrator step): the step coroutine genuinely
    `await`s an asyncio.Future until the user decides or the request expires.

Every request/resolution is published on the event bus (`approval` events) so the
dashboard can render an approval card alongside Freya's spoken question. First
resolution wins; the other path simply finds the action already gone.
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from core import runtime
from core.events import bus
from core.registry import tool, P, OBJ, STR


def _args_preview(args: dict, limit: int = 160) -> str:
    try:
        text = ", ".join(f"{k}={v}" for k, v in (args or {}).items())
    except Exception:
        text = json.dumps(args, default=str)
    return text[:limit] + ("…" if len(text) > limit else "")


@dataclass
class PendingAction:
    id: str
    summary: str
    tool: str
    args: dict
    source: str  # "live" | "mission:<id>" | "suggestion"
    expires_at: float
    thunk: Optional[Callable[[], Awaitable[str]]] = None  # live path
    future: Optional[asyncio.Future] = None               # mission path
    timeout_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "tool": self.tool,
            "argsPreview": _args_preview(self.args),
            "source": self.source,
            "expiresAt": self.expires_at,
        }


class ApprovalManager:
    def __init__(self):
        self._pending: dict[str, PendingAction] = {}

    # ── Requesting ─────────────────────────────────────────────────────────

    def request_deferred(self, summary: str, tool_name: str, args: dict,
                         thunk: Callable[[], Awaitable[str]],
                         timeout: float = 120.0, source: str = "live") -> str:
        """LIVE path: park the action and return its id immediately."""
        action = self._add(summary, tool_name, args, source, timeout, thunk=thunk)
        return action.id

    async def wait(self, summary: str, tool_name: str, args: dict,
                   source: str, timeout: float = 120.0) -> bool:
        """MISSION path: block the calling step until decided or expired."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        action = self._add(summary, tool_name, args, source, timeout, future=future)
        # Ask out loud too — the user may be away from the dashboard.
        runtime.announce(
            f"[APPROVAL NEEDED] A background mission wants to: {summary}. "
            f"Ask the user briefly whether to go ahead, and call approve_action or "
            f"reject_action with action_id '{action.id}' based on his answer."
        )
        try:
            return await future
        except asyncio.CancelledError:
            self._pending.pop(action.id, None)
            if action.timeout_task:
                action.timeout_task.cancel()
            bus.publish_soon("approval", {"event": "resolved", "id": action.id,
                "approved": False, "via": "cancelled"})
            raise

    def _add(self, summary, tool_name, args, source, timeout, thunk=None, future=None) -> PendingAction:
        action = PendingAction(
            id=f"a-{uuid.uuid4().hex[:8]}",
            summary=summary,
            tool=tool_name,
            args=args or {},
            source=source,
            expires_at=time.time() + timeout,
            thunk=thunk,
            future=future,
        )
        self._pending[action.id] = action
        action.timeout_task = asyncio.get_running_loop().create_task(
            self._expire_after(action.id, timeout)
        )
        bus.publish_soon("approval", {"event": "requested", **action.to_payload()})
        # Body language: the avatar snaps to an alert stance while waiting.
        bus.publish_soon("avatar", {"intent": "expression", "name": "alert", "intensity": 0.8})
        return action

    async def _expire_after(self, action_id: str, timeout: float):
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            return
        action = self._pending.pop(action_id, None)
        if action is None:
            return
        if action.future is not None and not action.future.done():
            action.future.set_result(False)
        await bus.publish("approval", {"event": "resolved", "id": action_id,
                                       "approved": False, "via": "timeout"})
        await runtime.inject(
            f"[The approval request '{action.summary}' expired without an answer, "
            f"so I let it lapse. Mention this briefly.]"
        )

    # ── Resolving ──────────────────────────────────────────────────────────

    async def resolve(self, action_id: str, approved: bool, via: str) -> Optional[str]:
        """Decide a pending action. Returns the executed result (live path,
        approved) or None. `via` is 'voice' | 'ui'."""
        action = self._pending.pop(action_id, None)
        if action is None:
            return None
        if action.timeout_task:
            action.timeout_task.cancel()

        await bus.publish("approval", {"event": "resolved", "id": action.id,
                                       "approved": approved, "via": via})

        if action.future is not None:  # mission path
            if not action.future.done():
                action.future.set_result(approved)
            return None

        # Live path — run the deferred work now (only on approval).
        if not approved:
            if via == "ui":
                await runtime.inject(
                    f"[the user denied '{action.summary}' from the dashboard. Acknowledge briefly.]"
                )
            return "Denied."
        try:
            result = await action.thunk() if action.thunk else "Approved (nothing to run)."
        except Exception as e:
            result = f"Approved, but the action failed: {e}"
        if via == "ui":
            # Result can't ride the original tool response — narrate it instead.
            await runtime.inject(
                f"[the user approved '{action.summary}' from the dashboard. It ran with "
                f"result: {result}. Tell him the outcome naturally.]"
            )
        return result

    # ── Introspection ──────────────────────────────────────────────────────

    def pending(self) -> list[PendingAction]:
        return sorted(self._pending.values(), key=lambda a: a.expires_at)

    def latest(self) -> Optional[PendingAction]:
        items = self.pending()
        return items[-1] if items else None


approvals = ApprovalManager()


# ══════════════════════════════════════════════════════════════════════════
#  Voice tools — how Freya herself confirms or cancels pending actions
# ══════════════════════════════════════════════════════════════════════════

def _pick(action_id: str | None) -> Optional[PendingAction]:
    if action_id:
        return approvals._pending.get(action_id)
    return approvals.latest()


@tool(
    "approve_action",
    "Confirm a pending action after he says yes. Use the action_id from APPROVAL_REQUIRED, or "
    "omit it for the latest. Returns the real result — relay it.",
    OBJ({"action_id": P(STR, "The pending action id, e.g. 'a-1b2c3d4e'.")}),
)
async def approve_action(args, ctx):
    action = _pick(args.get("action_id"))
    if action is None:
        return "There is no pending action to approve."
    result = await approvals.resolve(action.id, True, via="voice")
    return result if result is not None else f"Approved — the mission is continuing with '{action.summary}'."


@tool(
    "reject_action",
    "Cancel a pending action after the user says no. Omit action_id to reject the most "
    "recent request.",
    OBJ({"action_id": P(STR)}),
)
async def reject_action(args, ctx):
    action = _pick(args.get("action_id"))
    if action is None:
        return "There is no pending action to reject."
    await approvals.resolve(action.id, False, via="voice")
    return f"Cancelled: {action.summary}."


@tool(
    "list_pending_actions",
    "List actions currently waiting for the user's approval.",
)
async def list_pending_actions(args, ctx):
    items = approvals.pending()
    if not items:
        return "Nothing is waiting for approval."
    return "\n".join(f"{a.id}: {a.summary} (from {a.source})" for a in items)
