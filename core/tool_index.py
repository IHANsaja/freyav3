"""Deferred tool loading for the Live session.

Every declaration sent at session setup is paid for on every turn and again on
every resume, and Gemini Live cannot add declarations mid-session. So instead
of sending all ~120 full schemas, the session gets:

  * a small CORE set of full declarations (things used nearly every turn and
    things whose latency matters in voice),
  * a one-line-per-skill INDEX of every other tool name in the system prompt,
  * two fixed tools: `search_tools` (returns full schemas on demand) and
    `run_tool` (calls a deferred tool through the normal registry dispatch, so
    gates, safety refusals and approvals all still apply).

Config (config/freya_config.json):
    "tool_index": {
        "enabled": true,
        "core_tools": ["remember", ...]   # optional; replaces DEFAULT_CORE
    }
"""
import json
import re

from google.genai import types

from core.registry import tool, OBJ, P, STR, INT, dispatch, build_declarations, _REGISTRY

# Chosen for per-turn use (avatar, approvals, memory) or voice latency.
DEFAULT_CORE = [
    "approve_action", "reject_action", "list_pending_actions",
    "set_expression", "set_gesture", "set_idle_state", "trigger_emphasis",
    "trigger_thinking", "trigger_listening",
    "remember", "recall_conversation", "list_memories",
    "web_search", "web_fetch", "get_weather",
    "open_app", "close_app", "capture_screen", "get_active_window",
    "set_volume", "media_control", "pause_listening", "switch_mode",
    "start_mission", "dispatch_agent",
    # A ringing call can't wait for a tool search.
    "answer_call", "speak_in_my_voice",
]
SEARCH_TOOLS = "search_tools"
RUN_TOOL = "run_tool"
_FIXED = {SEARCH_TOOLS, RUN_TOOL}


def _cfg(config: dict) -> dict:
    return (config or {}).get("tool_index") or {}


def enabled(config: dict) -> bool:
    return bool(_cfg(config).get("enabled", False))


def _core_names(config: dict) -> set[str]:
    return set(_cfg(config).get("core_tools") or DEFAULT_CORE) | _FIXED


def _all_declarations(config: dict) -> list[types.FunctionDeclaration]:
    from core.model import TOOL_DECLARATIONS  # local: model.py imports this module
    return [d for d in TOOL_DECLARATIONS + build_declarations(config) if d.name not in _FIXED]


def _fixed_declarations() -> list[types.FunctionDeclaration]:
    return [_REGISTRY[n]["decl"] for n in (SEARCH_TOOLS, RUN_TOOL)]


def split(declarations: list, config: dict) -> tuple[list, list]:
    """(sent in full, deferred). Disabled → everything sent, as before."""
    declarations = [d for d in declarations if d.name not in _FIXED]
    if not enabled(config):
        return declarations, []
    core = _core_names(config)
    loaded = [d for d in declarations if d.name in core]
    deferred = [d for d in declarations if d.name not in core]
    if not deferred:
        return loaded, []
    return loaded + _fixed_declarations(), deferred


def _skill_of(name: str) -> str:
    if name.startswith("mcp__"):
        return "mcp"
    entry = _REGISTRY.get(name)
    return (entry or {}).get("skill") or "system"


def index_prompt(deferred: list) -> str:
    """Compact index: one line per skill, names only."""
    if not deferred:
        return ""
    try:
        from core.skills.loader import load_all
        manifests = load_all()
    except Exception:
        manifests = {}
    groups: dict[str, list[str]] = {}
    for d in deferred:
        groups.setdefault(_skill_of(d.name), []).append(d.name)
    lines = []
    for skill, names in sorted(groups.items()):
        m = manifests.get(skill)
        label = m.name if m else skill
        lines.append(f"- {label}: {', '.join(sorted(names))}")
    return (
        "MORE TOOLS: besides the tools you can call directly, these exist. To use one, "
        "call search_tools (by name or by what you need) to get its parameters, then call "
        "run_tool with its name and arguments. Never say you lack a capability without "
        "checking this list or searching first. Instructions elsewhere that name one of "
        "these tools mean: call it through run_tool.\n" + "\n".join(lines)
    )


# ── schema helpers ────────────────────────────────────────────────────────────

def _schema(s) -> dict:
    if s is None:
        return {}
    out = {}
    t = getattr(s, "type", None)
    if t is not None:
        out["type"] = str(getattr(t, "value", t)).lower()
    if getattr(s, "description", None):
        out["description"] = s.description
    if getattr(s, "enum", None):
        out["enum"] = list(s.enum)
    if getattr(s, "items", None) is not None:
        out["items"] = _schema(s.items)
    if getattr(s, "properties", None):
        out["properties"] = {k: _schema(v) for k, v in s.properties.items()}
    if getattr(s, "required", None):
        out["required"] = list(s.required)
    return out


def _describe(d) -> dict:
    params = _schema(d.parameters)
    return {"name": d.name, "skill": _skill_of(d.name), "description": d.description or "",
            "parameters": params.get("properties", {}), "required": params.get("required", [])}


_WORD = re.compile(r"[a-z0-9]+")


def _score(query_words: set[str], d) -> float:
    name = d.name.lower()
    hay = f"{name} {_skill_of(d.name)} {d.description or ''}".lower()
    words = set(_WORD.findall(hay))
    name_words = set(_WORD.findall(name))
    score = 0.0
    for q in query_words:
        if q == name:
            score += 10
        if q in name_words:
            score += 3
        elif q in words:
            score += 1
        elif any(w.startswith(q) for w in words if len(q) >= 3):
            score += 0.5
    return score


async def _semantic_hits(query: str, ranked: list, limit: int, config: dict) -> list:
    """Tools Jev thinks fit the query, best first. [] when Jev is off or unsure."""
    from core import systemone
    if not systemone.enabled(config, "tool_routing"):
        return []
    # Choice caps at 255 options; keyword order decides who makes the cut.
    pool = ranked[:255]
    options = {d.name: (d.description or "")[:240] or None for d in pool}
    answer = await systemone.choice(
        query,
        "Which tool best does what this request asks for?",
        options, config, "tool_routing",
    )
    if not answer:
        return []
    min_p = float(systemone.setting(config, "tool_routing", "min_probability", 0.05))
    probs = sorted(answer["probabilities"].items(), key=lambda kv: -kv[1])
    by_name = {d.name: d for d in pool}
    return [by_name[n] for n, p in probs[:limit] if p >= min_p and n in by_name]


def _coerce(value, spec: dict):
    t = spec.get("type")
    try:
        if t == "integer" and isinstance(value, str):
            return int(value)
        if t == "number" and isinstance(value, str):
            return float(value)
        if t == "boolean" and isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
    except ValueError:
        pass
    return value


# ── the two fixed tools ───────────────────────────────────────────────────────

@tool(SEARCH_TOOLS,
      "Find tools that are not directly callable and get their full parameters. Query by "
      "tool name(s) or by what you want to do (e.g. 'schedule reminder', 'draw_on_chart'). "
      "Then call run_tool.",
      OBJ({"query": P(STR, "Tool names (comma separated) or keywords"),
           "limit": P(INT, "Max results, default 5")}, ["query"]))
async def search_tools(args, ctx):
    query = str(args.get("query") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 5), 15))
    decls = _all_declarations(ctx.config)
    by_name = {d.name.lower(): d for d in decls}
    exact = [by_name[n.strip()] for n in query.split(",") if n.strip() in by_name]
    if exact:
        hits = exact[:15]
    else:
        qw = set(_WORD.findall(query))
        ranked = sorted(((_score(qw, d), d) for d in decls), key=lambda x: -x[0])
        keyword_hits = [d for s, d in ranked if s > 0]
        # Jev matches on meaning ("check my inbox" → an email tool whose
        # description never says inbox); keywords fill whatever it leaves.
        semantic = await _semantic_hits(query, [d for _, d in ranked], limit, ctx.config)
        hits = list({d.name: d for d in semantic + keyword_hits}.values())[:limit]
    if not hits:
        return f"No tools match '{query}'. Try different keywords."
    return json.dumps([_describe(d) for d in hits], ensure_ascii=False)


@tool(RUN_TOOL,
      "Run a tool found via search_tools or the MORE TOOLS list. `arguments` is a JSON "
      "object string with that tool's parameters, e.g. {\"query\": \"x\"}.",
      OBJ({"name": P(STR, "Exact tool name"),
           "arguments": P(STR, "JSON object of arguments, '{}' if none")}, ["name"]))
async def run_tool(args, ctx):
    name = str(args.get("name") or "").strip()
    if name in _FIXED:
        return f"{name} is called directly, not through run_tool."
    decl = next((d for d in _all_declarations(ctx.config) if d.name == name), None)
    if decl is None:
        return f"Unknown or disabled tool '{name}'. Use search_tools to find the right name."

    raw = args.get("arguments")
    if isinstance(raw, dict):
        # She sometimes sends the object with its keys still JSON-quoted:
        # {'"path"': 'C:\\...'} — which then "missed" a required argument.
        call_args = {str(k).strip().strip("\"'"): v for k, v in raw.items()}
    else:
        try:
            call_args = json.loads(raw) if raw and str(raw).strip() else {}
        except json.JSONDecodeError as e:
            return f"arguments is not valid JSON ({e}). Pass a JSON object string."
        if not isinstance(call_args, dict):
            return "arguments must be a JSON object."

    spec = _schema(decl.parameters)
    props = spec.get("properties", {})
    missing = [r for r in spec.get("required", []) if r not in call_args]
    if missing:
        return (f"Missing required argument(s) for {name}: {', '.join(missing)}. "
                f"Parameters: {json.dumps(props, ensure_ascii=False)}")
    unknown = [k for k in call_args if props and k not in props]
    if unknown:
        return (f"Unknown argument(s) for {name}: {', '.join(unknown)}. "
                f"Parameters: {json.dumps(props, ensure_ascii=False)}")
    call_args = {k: _coerce(v, props.get(k, {})) for k, v in call_args.items()}

    # Full registry path: gates, safety refusals and approval prompts all apply.
    return await dispatch(name, call_args, ctx)
