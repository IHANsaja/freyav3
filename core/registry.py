"""
Dynamic async tool registry — the spine of Freya's "superagent" tool system.

Why this exists
---------------
Originally Freya's tools were hardcoded in two places: a `TOOL_DECLARATIONS` list in
`core/model.py` and a giant `if/elif` chain in `core/tools.py:dispatch`. That made it
impossible to (a) add tools at runtime (MCP servers, self-written skills) and (b) run
long tasks (sub-agents, browser-use) without freezing the audio loop, because dispatch
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
    """A single property schema."""
    return types.Schema(type=type_, description=description, **kw)


def OBJ(properties: dict | None = None, required: list | None = None) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties or {},
        required=required or [],
    )


# ── Tool context passed to every handler ──────────────────────────────────
class ToolContext:
    """Everything a handler might need: config + channels to the live session."""

    def __init__(self, config: dict, session=None):
        self.config = config
        self.session = session

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
#          "gate": "a.b.c"|None, "dangerous": bool}
_REGISTRY: dict[str, dict] = {}
_skills_loaded = False


def register(name, handler, decl=None, *, gate=None, dangerous=False):
    """Register a handler. If `decl` is None it's a handler-only override of an
    existing (statically declared) tool — dispatch will use it but it won't be
    re-declared to Gemini."""
    _REGISTRY[name] = {"decl": decl, "handler": handler, "gate": gate, "dangerous": dangerous}


def tool(name, description, parameters=None, *, gate=None, dangerous=False):
    """Decorator: declare + register a brand-new tool in one step."""
    decl = types.FunctionDeclaration(
        name=name,
        description=description,
        parameters=parameters or OBJ(),
    )

    def deco(fn):
        register(name, fn, decl=decl, gate=gate, dangerous=dangerous)
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
    """Import every skill module once so they self-register. Missing optional
    dependencies degrade gracefully (the module just won't register its tools)."""
    global _skills_loaded
    if _skills_loaded:
        return
    _skills_loaded = True
    modules = [
        "core.news",
        "core.system_tools",
        "core.screen",
        "core.agents",
        "core.browser_agent",
        "core.rag_memory",
        "core.scheduler",
        "core.ambient",
        "core.self_extend",
        "core.listening_tools",
        "core.web",
    ]
    for mod in modules:
        try:
            __import__(mod)
        except Exception as e:
            print(f"  [registry] skill '{mod}' unavailable: {e}")
    # Hot-load any custom tools Freya wrote in previous sessions.
    try:
        from core.self_extend import load_custom_tools
        load_custom_tools()
    except Exception:
        pass


def build_declarations(config: dict) -> list[types.FunctionDeclaration]:
    """All NEW tool declarations to merge with model.py's static list."""
    _load_skills()
    decls = []
    for entry in _REGISTRY.values():
        if entry["decl"] is not None and _gate_open(entry["gate"], config):
            decls.append(entry["decl"])
    # Live MCP-server tools
    try:
        from core.mcp_client import mcp_manager
        decls.extend(mcp_manager.get_declarations())
    except Exception:
        pass
    return decls


async def dispatch(name: str, args: dict, ctx: ToolContext) -> str:
    """Route a Gemini function call. Async-aware, with legacy fallback."""
    _load_skills()
    entry = _REGISTRY.get(name)

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
            return msg

    handler = entry["handler"]
    try:
        if inspect.iscoroutinefunction(handler):
            return await handler(args, ctx)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: handler(args, ctx))
    except Exception as e:
        return f"Tool error in {name}: {e}"


def registered_names() -> list[str]:
    return sorted(_REGISTRY.keys())
