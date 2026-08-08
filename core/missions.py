"""
Mission orchestrator — high-level goals executed as plan → execute → verify → report.

`dispatch_agent` (core/agents.py) stays the tool for quick single-shot delegations.
Missions are for goals that need decomposition: the orchestrator plans concrete steps
with one JSON-schema Gemini call, runs each step through the shared ReAct executor
(`agents.react_loop`) with a curated agent spec, verifies the outcome with a cheap
model before moving on, and finally reports in Freya's voice.

Everything runs in a background asyncio task (same pattern as sub-agents) so the live
audio loop never blocks. Sensitive steps pause on the approval gate automatically:
step tool calls carry `ToolContext(source="mission:<id>")`, which makes
`registry.dispatch` await the user's decision instead of deferring.

Every state change is published as a `mission` event on the bus for the dashboard's
reasoning panel; spoken updates are limited to milestones (plan ready, approval
needed, done/failed) so Freya doesn't narrate every step.
"""

import asyncio
import itertools
import json
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from google import genai
from google.genai import types

from config import get_agent_api_key
from core import runtime
from core.agents import DEFAULT_AGENTS, _spec, react_loop, quota_hit
from core.registry import tool, ToolContext, OBJ, P, STR

StepStatus = Literal["pending", "running", "verifying", "awaiting_approval",
                     "done", "failed", "skipped"]
MissionStatus = Literal["planning", "running", "awaiting_approval", "verifying",
                        "done", "failed", "cancelled"]

PLANNER_MODEL_DEFAULT = "gemini-flash-latest"
VERIFIER_MODEL_DEFAULT = "gemini-flash-lite-latest"
MAX_PLAN_STEPS = 6
MAX_STEP_ATTEMPTS = 2

_counter = itertools.count(1)


@dataclass
class MissionStep:
    id: int
    title: str
    detail: str
    agent_type: str = "researcher"
    sensitive: bool = False
    status: StepStatus = "pending"
    attempts: int = 0
    result: Optional[str] = None
    verification: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "id": self.id, "title": self.title, "detail": self.detail,
            "status": self.status, "sensitive": self.sensitive,
            "result": (self.result or "")[:400] or None,
            "verification": self.verification,
        }


@dataclass
class Mission:
    id: str
    goal: str
    status: MissionStatus = "planning"
    steps: list[MissionStep] = field(default_factory=list)
    current_step: int = 0
    report: Optional[str] = None
    created: float = field(default_factory=time.time)
    task: Optional[asyncio.Task] = field(default=None, repr=False)

    def to_payload(self) -> dict:
        return {
            "id": self.id, "goal": self.goal, "status": self.status,
            "currentStep": self.current_step, "report": self.report,
            "steps": [s.to_payload() for s in self.steps],
        }


def _agent_menu(config: dict) -> str:
    lines = []
    for name in DEFAULT_AGENTS:
        spec = _spec(name, config)
        lines.append(f"- {name}: tools {', '.join(spec.get('tools', []))}")
    return "\n".join(lines)


_PLAN_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING,
                                  description="Short imperative step name (3-6 words)"),
            "detail": types.Schema(type=types.Type.STRING,
                                   description="Full self-contained instruction for the step executor"),
            "agent_type": types.Schema(type=types.Type.STRING,
                                       description="Which agent runs this step: researcher, coder, or operator"),
            "sensitive": types.Schema(type=types.Type.BOOLEAN,
                                      description="True if the step sends/submits/deletes/changes something outside the project"),
        },
        required=["title", "detail", "agent_type"],
    ),
)


class MissionOrchestrator:
    def __init__(self):
        self._missions: dict[str, Mission] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self, goal: str, config: dict) -> Mission:
        mission = Mission(id=f"m-{next(_counter)}", goal=goal.strip())
        self._missions[mission.id] = mission
        await self._publish(mission, "created")
        mission.task = asyncio.create_task(self._run(mission, config))
        return mission

    def cancel(self, mission_id: str) -> Optional[Mission]:
        mission = self._missions.get(mission_id)
        if mission is None or mission.status in ("done", "failed", "cancelled"):
            return None
        if mission.task:
            mission.task.cancel()
        return mission

    def get(self, mission_id: Optional[str] = None) -> Optional[Mission]:
        if mission_id:
            return self._missions.get(mission_id)
        active = [m for m in self._missions.values()
                  if m.status not in ("done", "failed", "cancelled")]
        pool = active or list(self._missions.values())
        return max(pool, key=lambda m: m.created) if pool else None

    def all(self) -> list[Mission]:
        return sorted(self._missions.values(), key=lambda m: m.created)

    # ── Run loop ───────────────────────────────────────────────────────────

    async def _run(self, mission: Mission, config: dict):
        try:
            await self._plan(mission, config)
            if not mission.steps:
                mission.status = "failed"
                mission.report = "I couldn't break that goal into steps."
                await self._publish(mission, "status")
                await runtime.inject(
                    f"[Mission '{mission.goal}' failed: you couldn't form a plan. Tell the user briefly.]"
                )
                return

            await runtime.inject(
                f"[Mission plan ready for '{mission.goal}': "
                + "; ".join(f"{s.id}. {s.title}" for s in mission.steps)
                + ". Give the user a one-sentence heads-up that you're starting.]"
            )
            await runtime.emit("avatar", {"intent": "state", "name": "working"})

            for step in mission.steps:
                mission.current_step = step.id
                ok = await self._execute_step(mission, step, config)
                if not ok and step.status == "failed":
                    mission.status = "failed"
                    break
            else:
                mission.status = "done"

            await self._report(mission, config)

        except asyncio.CancelledError:
            mission.status = "cancelled"
            for step in mission.steps:
                if step.status in ("pending", "running", "verifying", "awaiting_approval"):
                    step.status = "skipped"
            await self._publish(mission, "status")
            await runtime.inject(f"[Mission '{mission.goal}' was cancelled. Acknowledge briefly.]")
        except Exception as e:
            mission.status = "failed"
            mission.report = ("I hit the Gemini quota mid-mission." if quota_hit(e)
                              else f"The mission hit an error: {e}")
            await self._publish(mission, "status")
            await runtime.inject(
                f"[Mission '{mission.goal}' failed: {mission.report}. Tell the user briefly.]"
            )
        finally:
            await runtime.emit(
                "avatar",
                {"intent": "gesture", "name": "celebrate"} if mission.status == "done"
                else {"intent": "state", "name": "idle"},
            )

    # ── Phases ─────────────────────────────────────────────────────────────

    async def _plan(self, mission: Mission, config: dict):
        mcfg = (config or {}).get("missions", {})
        client = genai.Client(api_key=get_agent_api_key())
        prompt = (
            f"Break this goal into at most {mcfg.get('max_plan_steps', MAX_PLAN_STEPS)} concrete, "
            f"sequential steps. Each step must be independently executable by ONE background agent "
            f"and verifiable from its output. Do not add filler steps (no 'review results' step at "
            f"the end — verification is automatic). Available agents:\n{_agent_menu(config)}\n\n"
            f"Mark a step sensitive if it sends, submits, deletes or changes anything outside this "
            f"machine's Freya project.\n\nGOAL: {mission.goal}"
        )
        resp = await client.aio.models.generate_content(
            model=mcfg.get("planner_model", PLANNER_MODEL_DEFAULT),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_PLAN_SCHEMA,
                temperature=0.2,
            ),
        )
        raw = json.loads(resp.text or "[]")
        for i, item in enumerate(raw[: mcfg.get("max_plan_steps", MAX_PLAN_STEPS)], start=1):
            agent = str(item.get("agent_type", "researcher")).lower()
            mission.steps.append(MissionStep(
                id=i,
                title=str(item.get("title", f"Step {i}"))[:80],
                detail=str(item.get("detail", "")),
                agent_type=agent if agent in DEFAULT_AGENTS else "researcher",
                sensitive=bool(item.get("sensitive", False)),
            ))
        mission.status = "running"
        await self._publish(mission, "plan")

    async def _execute_step(self, mission: Mission, step: MissionStep, config: dict) -> bool:
        spec = _spec(step.agent_type, config)
        ctx = ToolContext(config, session=None, source=f"mission:{mission.id}")
        evidence: list[str] = []

        async def on_tool(name, args, result):
            evidence.append(f"{name}({json.dumps(args, default=str)[:120]}) -> {result[:300]}")
            await self._publish(mission, "step")

        prior = "\n".join(
            f"Step {s.id} ({s.title}): {(s.result or '')[:300]}"
            for s in mission.steps if s.status == "done"
        )
        feedback = ""
        while step.attempts < MAX_STEP_ATTEMPTS:
            step.attempts += 1
            step.status = "running"
            await self._publish(mission, "step")
            task_text = (
                f"OVERALL GOAL: {mission.goal}\n"
                + (f"COMPLETED SO FAR:\n{prior}\n" if prior else "")
                + f"YOUR STEP: {step.detail}\n"
                + (f"PREVIOUS ATTEMPT WAS REJECTED: {feedback}\nFix that this time.\n" if feedback else "")
                + "Do only this step, then answer with a factual summary of what you did and found."
            )
            try:
                # Track approval pauses: registry flips nothing itself, so watch
                # the pending queue while the step runs.
                waiter = asyncio.create_task(self._watch_approvals(mission, step))
                try:
                    step.result = await react_loop(
                        spec["system"], task_text, spec.get("tools", []),
                        spec["model"], config, ctx, on_tool=on_tool,
                    )
                finally:
                    waiter.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if quota_hit(e):
                    raise
                step.result = f"Step error: {e}"

            step.status = "verifying"
            mission.status = "verifying"
            await self._publish(mission, "step")
            verified, reason = await self._verify_step(mission, step, evidence, config)
            step.verification = reason
            if verified:
                step.status = "done"
                mission.status = "running"
                await self._publish(mission, "step")
                return True
            feedback = reason

        step.status = "failed"
        mission.status = "running"
        await self._publish(mission, "step")
        return False

    async def _watch_approvals(self, mission: Mission, step: MissionStep):
        """Reflect the approval gate in mission/step status while a step runs."""
        from core.approvals import approvals
        source = f"mission:{mission.id}"
        was_waiting = False
        while True:
            waiting = any(a.source == source for a in approvals.pending())
            if waiting != was_waiting:
                was_waiting = waiting
                step.status = "awaiting_approval" if waiting else "running"
                mission.status = "awaiting_approval" if waiting else "running"
                await self._publish(mission, "step")
            await asyncio.sleep(0.5)

    async def _verify_step(self, mission: Mission, step: MissionStep,
                           evidence: list[str], config: dict) -> tuple[bool, str]:
        mcfg = (config or {}).get("missions", {})
        schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "verified": types.Schema(type=types.Type.BOOLEAN),
                "reason": types.Schema(type=types.Type.STRING),
            },
            required=["verified", "reason"],
        )
        prompt = (
            "You are a strict verifier. Did the executed step plausibly accomplish its "
            "instruction, judging ONLY from its summary and tool evidence? Be tolerant of "
            "style, intolerant of missing substance (empty results, errors, refusals, "
            "declined approvals).\n"
            f"STEP INSTRUCTION: {step.detail}\n"
            f"EXECUTOR SUMMARY: {(step.result or '')[:1500]}\n"
            f"TOOL EVIDENCE:\n" + "\n".join(evidence[-12:])
        )
        try:
            client = genai.Client(api_key=get_agent_api_key())
            resp = await client.aio.models.generate_content(
                model=mcfg.get("verifier_model", VERIFIER_MODEL_DEFAULT),
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                ),
            )
            data = json.loads(resp.text or "{}")
            return bool(data.get("verified")), str(data.get("reason", ""))[:300]
        except Exception as e:
            # Verifier unavailable → don't block the mission on it.
            return True, f"(verification skipped: {e})"

    async def _report(self, mission: Mission, config: dict):
        done = [s for s in mission.steps if s.status == "done"]
        failed = [s for s in mission.steps if s.status == "failed"]
        raw = "\n".join(f"{s.title}: {(s.result or '')[:400]}" for s in mission.steps)
        summary = None
        try:
            mcfg = (config or {}).get("missions", {})
            client = genai.Client(api_key=get_agent_api_key())
            resp = await client.aio.models.generate_content(
                model=mcfg.get("verifier_model", VERIFIER_MODEL_DEFAULT),
                contents=(
                    "Summarize this mission outcome in 2-3 spoken-friendly sentences, "
                    "facts first, no markdown.\n"
                    f"GOAL: {mission.goal}\nSTATUS: {mission.status}\nSTEP RESULTS:\n{raw[:6000]}"
                ),
            )
            summary = (resp.text or "").strip() or None
        except Exception:
            pass
        mission.report = summary or (
            f"Finished {len(done)}/{len(mission.steps)} steps"
            + (f"; failed on: {failed[0].title}" if failed else "") + "."
        )
        await self._publish(mission, "report")
        await runtime.inject(
            f"[Mission '{mission.goal}' {mission.status}. Report to the user naturally: {mission.report}]"
        )

    async def _publish(self, mission: Mission, event: str):
        await runtime.emit("mission", {"event": event, "mission": mission.to_payload()})


missions = MissionOrchestrator()


# ══════════════════════════════════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════════════════════════════════

@tool(
    "start_mission",
    "Start a mission for a big goal needing several planned steps ('prepare my presentation'). "
    "It plans, executes, verifies and reports back, pausing for approval on sensitive steps. "
    "For a single task use dispatch_agent.",
    OBJ({"goal": P(STR, "The complete high-level goal, with any constraints the user mentioned")},
        ["goal"]),
)
async def start_mission(args, ctx) -> str:
    goal = (args.get("goal") or "").strip()
    if not goal:
        return "Give the mission a goal."
    mission = await missions.start(goal, ctx.config)
    return (f"Mission {mission.id} started: {goal}. I'm planning the steps now and will "
            "give a heads-up when the plan is ready. Progress shows on the dashboard.")


@tool(
    "mission_status",
    "Check progress of a running mission (or the most recent one if no id is given).",
    OBJ({"mission_id": P(STR, "Mission id like 'm-1' (optional)")}),
)
async def mission_status(args, ctx) -> str:
    mission = missions.get(args.get("mission_id"))
    if mission is None:
        return "No missions have been started yet."
    lines = [f"Mission {mission.id} ({mission.status}): {mission.goal}"]
    for s in mission.steps:
        lines.append(f"  {s.id}. {s.title} — {s.status}")
    if mission.report:
        lines.append(f"Report: {mission.report}")
    return "\n".join(lines)


@tool(
    "cancel_mission",
    "Cancel a running mission (or the most recent one if no id is given).",
    OBJ({"mission_id": P(STR, "Mission id like 'm-1' (optional)")}),
)
async def cancel_mission(args, ctx) -> str:
    target = missions.get(args.get("mission_id"))
    if target is None:
        return "There's no mission to cancel."
    cancelled = missions.cancel(target.id)
    if cancelled is None:
        return f"Mission {target.id} already finished ({target.status})."
    return f"Cancelling mission {target.id}: {target.goal}."
