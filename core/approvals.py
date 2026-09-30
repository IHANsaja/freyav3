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
    risk: Optional[int] = None  # 1-5 from Jev; advisory only, never auto-approves
    # Only a dashboard click may approve it. Set while a call is being handled:
    # the caller's voice comes out of the speakers, and Freya's mic could take
    # their "yes" as the user's.
    ui_only: bool = False

    def to_payload(self) -> dict:
        payload = {
            "id": self.id,
            "summary": self.summary,
            "tool": self.tool,
            "argsPreview": _args_preview(self.args),
            "source": self.source,
            "expiresAt": self.expires_at,
            "uiOnly": self.ui_only,
        }
        if self.risk is not None:
            payload["risk"] = self.risk
        return payload


_RISK_LEVELS = [
    "Harmless: read-only or trivially undone",
    "Low: a small change that is easy to undo",
    "Moderate: changes files, settings or apps in ways that take effort to undo",
    "High: sends or publishes something, spends money, or deletes data",
    "Severe: irreversible loss, security exposure, or money leaving the account",
]


_assessments: set[asyncio.Task] = set()  # keeps fire-and-forget tasks alive


async def _assess(action: "PendingAction"):
    """Rate how risky the parked action is, for the dashboard badge.

    Purely advisory: it changes what the card shows, never whether the action
    needs the user's yes.
    """
    from core import systemone
    try:
        from config import load_config
        config = load_config()
    except Exception:
        return
    result = await systemone.score(
        {"tool": action.tool, "summary": action.summary, "arguments": action.args,
         "requested_by": action.source},
        "How risky is it to run this action on the user's computer and accounts?",
        _RISK_LEVELS, config, "approval_risk",
    )
    if not result or action.id not in approvals._pending:
        return
    if result["confidence"] < float(systemone.setting(config, "approval_risk", "min_confidence", 0.4)):
        return
    action.risk = round(result["score"]) + 1
    await bus.publish("approval", {"event": "assessed", "id": action.id, "risk": action.risk})


class ApprovalManager:
    def __init__(self):
        self._pending: dict[str, PendingAction] = {}

    # ── Requesting ─────────────────────────────────────────────────────────

    def request_deferred(self, summary: str, tool_name: str, args: dict,
                         thunk: Callable[[], Awaitable[str]],
                         timeout: float = 120.0, source: str = "live",
                         ui_only: bool = False) -> str:
        """LIVE path: park the action and return its id immediately."""
        action = self._add(summary, tool_name, args, source, timeout, thunk=thunk,
                           ui_only=ui_only)
        return action.id

    async def wait(self, summary: str, tool_name: str, args: dict,
                   source: str, timeout: float = 120.0) -> bool:
        """MISSION path: block the calling step until decided or expired.

        The caller is now on the background loop, but the decision arrives on the
        main loop — a click on the dashboard or a spoken "yes" routed through
        `approve_action`. An asyncio.Future belongs to exactly one loop, so the
        whole wait is hosted on the main loop and the background step simply
        awaits the hop.
        """
        from core import background
        return await background.on_main(
            self._wait_on_main(summary, tool_name, args, source, timeout)
        )

    async def _wait_on_main(self, summary: str, tool_name: str, args: dict,
                            source: str, timeout: float = 120.0) -> bool:
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

    def _add(self, summary, tool_name, args, source, timeout, thunk=None, future=None,
             ui_only=False) -> PendingAction:
        action = PendingAction(
            id=f"a-{uuid.uuid4().hex[:8]}",
            summary=summary,
            tool=tool_name,
            args=args or {},
            source=source,
            expires_at=time.time() + timeout,
            thunk=thunk,
            future=future,
            ui_only=ui_only,
        )
        self._pending[action.id] = action
        action.timeout_task = asyncio.get_running_loop().create_task(
            self._expire_after(action.id, timeout)
        )
        bus.publish_soon("approval", {"event": "requested", **action.to_payload()})
        # Body language: the avatar snaps to an alert stance while waiting.
        bus.publish_soon("avatar", {"intent": "expression", "name": "alert", "intensity": 0.8})
        _assessments.add(t := asyncio.get_running_loop().create_task(_assess(action)))
        t.add_done_callback(_assessments.discard)
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
    if action.ui_only:
        return ("Not approved: this action can only be approved by clicking Approve on the "
                "dashboard, not by voice. Tell the user it is waiting for his click.")
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
