"""
Dynamic async tool registry — the spine of Freya's "superagent" tool system.

Why this exists
---------------
Originally Freya's tools were hardcoded in two places: a `TOOL_DECLARATIONS` list in
`core/model.py` and a giant `if/elif` chain in `core/tools.py:dispatch`. That made it
impossible to (a) add tools at runtime (MCP servers, self-written skills) and (b) run
long tasks (sub-agents, browsing) without freezing the audio loop, because dispatch
was synchronous.

This registry fixes both:
  • Tools self-register from skill modules on import (`@tool(...)` / `register(...)`).
  • Handlers may be sync OR async. Async handlers are awaited; sync ones run in an
    executor so PyAutoGUI/UIA/network calls never block the realtime audio coroutine.
  • `build_declarations(config)` assembles the live tool list = new skills + MCP tools +
    hot-loaded custom tools, each gated by a config flag.
  • `dispatch(name, args, ctx)` routes calls and falls back to the legacy
    `core/tools.py:dispatch` for the original 23 tools → fully backward compatible.

Handler contract:  handler(args: dict, ctx: ToolContext) -> str
"""

import asyncio
import inspect

from google.genai import types

# ── Schema sugar so skill modules stay terse ──────────────────────────────
STR = types.Type.STRING
INT = types.Type.INTEGER
NUM = types.Type.NUMBER
BOOL = types.Type.BOOLEAN
ARR = types.Type.ARRAY


def P(type_, description: str = "", **kw) -> types.Schema:
    """A single property schema.

    An empty description is dropped rather than serialized as `""`. Some
    parameters need no gloss — `path`, `url`, `query` say it themselves once the
    tool description is read — and every declaration is re-sent on every turn,
    so an empty field is pure tax.
    """
    return types.Schema(type=type_, description=description or None, **kw)


def OBJ(properties: dict | None = None, required: list | None = None) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties or {},
        required=required or [],
    )


# ── Tool context passed to every handler ──────────────────────────────────
class ToolContext:
    """Everything a handler might need: config + channels to the live session.

    `source` decides how the approval gate behaves for sensitive calls:
      "live"          → the voice session; approval must not block, so the call
                        returns an APPROVAL_REQUIRED token and defers the work.
      "mission:<id>"  → a background mission step; it genuinely awaits the
                        user's decision.
    """

    def __init__(self, config: dict, session=None, source: str = "live"):
        self.config = config
        self.session = session
        self.source = source

    async def inject(self, text: str):
        """Make Freya say `text` out loud now (proactive speech)."""
        from core import runtime
        await runtime.inject(text)

    async def emit(self, event_type: str, payload: dict):
        """Push a status event to the dashboard."""
        from core import runtime
        await runtime.emit(event_type, payload)


# ── The registry itself ────────────────────────────────────────────────────
# name -> {"decl": FunctionDeclaration|None, "handler": callable,
#          "gate": "a.b.c"|None, "dangerous": bool, "approval": str,
#          "skill": str|None}
_REGISTRY: dict[str, dict] = {}
_skills_loaded = False

# Set by core/skills/loader.py around each skill-module import so tools are
# stamped with their owning skill id (powers the skill catalog + toggles).
_current_skill: str | None = None


def register(name, handler, decl=None, *, gate=None, dangerous=False, approval="none"):
    """Register a handler. If `decl` is None it's a handler-only override of an
    existing (statically declared) tool — dispatch will use it but it won't be
    re-declared to Gemini. `approval="confirm"` forces the human approval gate
    for every call regardless of arguments."""
    _REGISTRY[name] = {"decl": decl, "handler": handler, "gate": gate,
                       "dangerous": dangerous, "approval": approval,
                       "skill": _current_skill}


def tool(name, description, parameters=None, *, gate=None, dangerous=False, approval="none"):
    """Decorator: declare + register a brand-new tool in one step."""
    decl = types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=parameters or OBJ(),
    )

    def deco(fn):
        register(name, fn, decl=decl, gate=gate, dangerous=dangerous, approval=approval)
        return fn

    return deco


def _gate_open(gate, config) -> bool:
    if not gate:
        return True
    node = config or {}
    for part in gate.split("."):
        if not isinstance(node, dict):
            return False
        node = node.get(part)
    return bool(node)


def _load_skills():
    """Import every skill once via the manifest-aware loader (core/skills/loader.py).
    Missing optional dependencies degrade gracefully."""
    global _skills_loaded
    if _skills_loaded:
        return
    _skills_loaded = True
    from core.skills.loader import load_all
    load_all()


def skill_catalog(config: dict) -> list[dict]:
    """Manifest + tool list + gate state for every skill (dashboard catalog)."""
    from core.skills.loader import catalog
    return catalog(config)


def build_declarations(config: dict) -> list[types.FunctionDeclaration]:
    """All NEW tool declarations to merge with model.py's static list.

    Two gates apply. A tool may carry its own `gate=`, and the SKILL that owns it
    may carry one in its manifest. Only the per-tool gate used to be enforced,
    so the dashboard's skill toggle silently did nothing for any skill whose
    tools didn't repeat the gate individually — `machine` and `scheduler` both.
    Turning "PC Knowledge" off wrote the flag, said "applies on next session
    start", and the tools came back anyway.
    """
    _load_skills()
    skill_gates = {}
    try:
        from core.skills.loader import load_all
        skill_gates = {m.id: m.gate for m in load_all().values() if m.gate}
    except Exception:
        pass

    decls = []
    for entry in _REGISTRY.values():
        if entry["decl"] is None:
            continue
        if not _gate_open(entry["gate"], config):
            continue
        if not _gate_open(skill_gates.get(entry.get("skill")), config):
            continue
        decls.append(entry["decl"])
    # Live MCP-server tools
    try:
        from core.mcp_client import mcp_manager
        decls.extend(mcp_manager.get_declarations())
    except Exception:
        pass
    return decls


async def _execute(name: str, args: dict, ctx: ToolContext, entry: dict | None) -> str:
    """Actually run the tool: registry handler, MCP call, or legacy fallback."""
    # MCP tools live outside the registry.
    if entry is None and name.startswith("mcp__"):
        try:
            from core.mcp_client import mcp_manager
            return await mcp_manager.call(name, args)
        except Exception as e:
            return f"MCP call failed: {e}"

    # Unknown to the registry → legacy dispatcher (the original 23 tools).
    if entry is None:
        try:
            from core.tools import dispatch as legacy_dispatch
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, legacy_dispatch, name, args, ctx.config)
        except Exception as e:
            return f"Unknown tool: {name} ({e})"

    # Safety gate for dangerous tools.
    if entry["dangerous"]:
        from core.safety import guard
        ok, msg = guard(name, args, ctx.config)
        if not ok:
            if ctx.source != "live":
                from core.execution import ExecutionError
                raise ExecutionError("Tool refused by safety policy")
            return msg

    handler = entry["handler"]
    try:
        if inspect.iscoroutinefunction(handler):
            return await handler(args, ctx)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: handler(args, ctx))
    except Exception as e:
        if ctx.source != "live":
            from core.execution import ExecutionError
            if isinstance(e, ExecutionError): raise
            raise ExecutionError(f"Tool failed: {name} ({type(e).__name__})") from e
        return f"Tool error in {name}: {e}"


async def dispatch(name: str, args: dict, ctx: ToolContext) -> str:
    """Route a Gemini function call. Async-aware, with legacy fallback.

    Sensitive calls hit the approval gate BEFORE execution — including legacy
    and MCP tools, which is why the check lives here and not in `_execute`.
    """
    _load_skills()
    entry = _REGISTRY.get(name)
    if entry is not None:
        from core.skills.loader import load_all
        manifest = load_all().get(entry.get("skill"))
        if not _gate_open(entry.get("gate"), ctx.config) or not _gate_open(
                manifest.gate if manifest else None, ctx.config):
            from core.execution import ExecutionError
            raise ExecutionError(f"Tool disabled: {name}")

    # Hard refusals come BEFORE the approval gate. Otherwise a write into
    # C:\Windows asked the user to approve it, waited for a yes, and only then
    # refused — pestering him for permission he was never able to grant, and
    # training him to click yes on prompts that don't mean anything.
    if entry is not None and entry["dangerous"]:
        try:
            from core.safety import guard
            ok, msg = guard(name, args, ctx.config)
            if not ok:
                if ctx.source != "live":
                    from core.execution import ExecutionError
                    raise ExecutionError("Tool refused by safety policy")
                return msg
        except Exception:
            pass  # a broken guard must not become a bypass — _execute re-checks

    try:
        from core.safety import needs_approval, describe_action
        gated = needs_approval(name, args, entry, ctx.config)
    except Exception as exc:
        from core.execution import ExecutionError
        raise ExecutionError("Unable to evaluate tool approval policy") from exc

    if gated:
        from core.approvals import approvals
        summary = describe_action(name, args)
        timeout = float((ctx.config or {}).get("safety", {}).get("approval_timeout_s", 120))

        if ctx.source == "live":
            async def thunk(name=name, args=args, ctx=ctx, entry=entry):
                return await _execute(name, args, ctx, entry)

            pid = approvals.request_deferred(summary, name, args, thunk, timeout=timeout)
            return (
                f"APPROVAL_REQUIRED[{pid}]: This is a sensitive action ({summary}) and it "
                f"has NOT run yet. Briefly tell the user what you're about to do and ask for a "
                f"yes or no. If he agrees, call approve_action with action_id '{pid}' — its "
                f"result is the real outcome. If he declines, call reject_action."
            )

        approved = await approvals.wait(summary, name, args, source=ctx.source, timeout=timeout)
        if not approved:
            from core.execution import ApprovalDenied
            raise ApprovalDenied("Action denied or approval expired; no automatic retry")

    return await _execute(name, args, ctx, entry)


def registered_names() -> list[str]:
    return sorted(_REGISTRY.keys())
