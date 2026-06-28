"""
Sub-agents — specialized background workers Freya delegates to.

The live voice model must stay responsive, so heavy multi-step work (deep research, a coding
task, driving the desktop) is handed to a background Gemini *text* agent running its own
tool-calling ReAct loop. Freya keeps chatting; when the sub-agent finishes it speaks the
result through the proactive channel (runtime.inject).

Each agent type has its own system prompt + a curated slice of the tool registry:
  • researcher — web/news/docs search, browser-use, semantic recall, file reading
  • coder      — read/write/edit files, run code, terminal, git
  • operator   — drive the desktop via UI-Automation (read_screen_elements + click_element…)

Types are overridable from config `sub_agents`. Reuses core/registry.dispatch for every tool
call, so sub-agents share the exact same tools as Freya herself.
"""

import asyncio
import itertools
import time

from google import genai
from google.genai import types

from config import get_api_key
from core import runtime
from core.registry import register, tool, dispatch as registry_dispatch, ToolContext, OBJ, P, STR

# Built-in agent specs (config `sub_agents.<type>` may override model/system/tools).
DEFAULT_AGENTS = {
    "researcher": {
        "model": "gemini-2.5-flash",
        "system": (
            "You are Freya's research sub-agent. Investigate the task thoroughly using your "
            "tools (web search, news, docs, the browser agent, semantic recall, reading files). "
            "Then write a tight, spoken-friendly briefing of what you found — facts first, no "
            "fluff, no markdown."
        ),
        "tools": ["browser_task", "get_world_news", "recall", "read_file", "search_files"],
    },
    "coder": {
        "model": "gemini-2.5-flash",
        "system": (
            "You are Freya's coding sub-agent. Complete the engineering task end to end: read the "
            "relevant files, make the change, run code/tests to verify. Be precise. Finish with a "
            "one-paragraph plain-English summary of what you changed and whether it worked."
        ),
        "tools": ["read_file", "write_file", "edit_file", "run_code", "list_dir",
                  "search_files", "run_terminal_command"],
    },
    "operator": {
        "model": "gemini-2.5-flash",
        "system": (
            "You are Freya's desktop-operator sub-agent. Drive the Windows GUI through the "
            "accessibility API — never guess coordinates. Workflow: focus_window to bring the "
            "target app forward; read_screen_elements or find_element to see the real controls; "
            "then control_element (click/type/toggle/select/expand) — it returns the result so "
            "you can VERIFY each step yourself before moving on. Re-scan after actions. Do not "
            "stop to ask for confirmation; complete the task, then summarize what you did."
        ),
        "tools": ["focus_window", "list_windows", "read_screen_elements", "find_element",
                  "control_element", "click_element", "click_text"],
    },
}

MAX_STEPS = 8
_counter = itertools.count(1)
_jobs: dict[str, dict] = {}  # id -> {type, task, status, result, started}


def _spec(agent_type: str, config: dict) -> dict:
    override = (config or {}).get("sub_agents", {}).get(agent_type, {})
    base = DEFAULT_AGENTS.get(agent_type, DEFAULT_AGENTS["researcher"]).copy()
    base.update({k: v for k, v in override.items() if v})
    return base


def _declarations(spec: dict, config: dict):
    """The FunctionDeclarations for this agent's allowed tools, pulled from the registry."""
    from core.registry import _REGISTRY, build_declarations
    build_declarations(config)  # ensure skills are loaded
    allowed = set(spec.get("tools", []))
    decls = []
    for name, entry in _REGISTRY.items():
        if name in allowed and entry["decl"] is not None:
            decls.append(entry["decl"])
    return decls


async def _run_agent(job_id: str, agent_type: str, task: str, config: dict):
    spec = _spec(agent_type, config)
    ctx = ToolContext(config, session=None)  # background: no realtime session
    client = genai.Client(api_key=get_api_key())
    decls = _declarations(spec, config)
    cfg = types.GenerateContentConfig(
        system_instruction=spec["system"],
        tools=[types.Tool(function_declarations=decls)] if decls else None,
        temperature=0.4,
    )
    contents = [types.Content(role="user", parts=[types.Part(text=task)])]

    final = "(no result)"
    try:
        for _step in range(MAX_STEPS):
            resp = await client.aio.models.generate_content(
                model=spec["model"], contents=contents, config=cfg
            )
            cand = (resp.candidates or [None])[0]
            if cand is None or cand.content is None:
                final = resp.text or "(empty response)"
                break
            parts = cand.content.parts or []
            fcalls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not fcalls:
                final = resp.text or "Done."
                break
            contents.append(cand.content)
            tool_parts = []
            for fc in fcalls:
                result = await registry_dispatch(fc.name, dict(fc.args or {}), ctx)
                await runtime.emit("agent", {"id": job_id, "type": agent_type,
                                             "step": fc.name, "status": "working"})
                tool_parts.append(types.Part(function_response=types.FunctionResponse(
                    name=fc.name, response={"result": str(result)[:4000]})))
            contents.append(types.Content(role="user", parts=tool_parts))
        else:
            final = "I ran out of steps before fully finishing that."
    except Exception as e:
        final = f"My {agent_type} agent hit an error: {e}"

    _jobs[job_id].update(status="done", result=final)
    await runtime.emit("agent", {"id": job_id, "type": agent_type, "status": "done"})
    await runtime.inject(f"Your {agent_type} agent finished the task '{task}'. Here's the result: {final}")


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "dispatch_agent",
    "Delegate a complex, multi-step task to a specialized background sub-agent so you can keep "
    "talking. Types: 'researcher' (deep web/news research), 'coder' (write/run code), 'operator' "
    "(drive the desktop GUI). The agent works in the background and will report back out loud when "
    "done. Tell Ihan you've dispatched it.",
    OBJ({"agent_type": P(STR, "researcher, coder, or operator"),
         "task": P(STR, "The full task for the sub-agent to accomplish")},
        ["agent_type", "task"]),
)
async def dispatch_agent(args, ctx) -> str:
    agent_type = (args.get("agent_type") or "researcher").lower().strip()
    task = (args.get("task") or "").strip()
    if agent_type not in DEFAULT_AGENTS and agent_type not in (ctx.config or {}).get("sub_agents", {}):
        return f"Unknown agent type '{agent_type}'. Use researcher, coder, or operator."
    if not task:
        return "Give the sub-agent a task to do."
    job_id = f"{agent_type[:3]}-{next(_counter)}"
    _jobs[job_id] = {"type": agent_type, "task": task, "status": "working",
                     "result": None, "started": time.time()}
    asyncio.create_task(_run_agent(job_id, agent_type, task, ctx.config))
    await ctx.emit("agent", {"id": job_id, "type": agent_type, "status": "started", "task": task})
    return (f"Dispatched the {agent_type} agent (job {job_id}) on: {task}. "
            "It's working in the background — I'll tell you when it's done.")


@tool("check_agents", "Check the status of background sub-agents you've dispatched.", OBJ())
def check_agents(args, ctx) -> str:
    if not _jobs:
        return "No sub-agents have been dispatched yet."
    lines = []
    for jid, j in _jobs.items():
        age = int(time.time() - j["started"])
        if j["status"] == "done":
            lines.append(f"{jid} ({j['type']}): done — {str(j['result'])[:160]}")
        else:
            lines.append(f"{jid} ({j['type']}): still working ({age}s) on '{j['task'][:60]}'")
    return "\n".join(lines)
