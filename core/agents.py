"""
Sub-agents — specialized background workers Freya delegates to.

The live voice model must stay responsive, so heavy multi-step work (deep research, a coding
task, driving the desktop) is handed to a background Gemini *text* agent running its own
tool-calling ReAct loop. Freya keeps chatting; when the sub-agent finishes it speaks the
result through the proactive channel (runtime.inject).

Each agent type has its own system prompt + a curated slice of the tool registry:
  • researcher — drives the real browser (core/browser) plus web/news search,
                 semantic recall and file reading
  • coder      — read/write/edit files, run code, terminal, git
  • operator   — drive the desktop via UI-Automation (read_screen_elements + click_element…)

Types are overridable from config `sub_agents`. Reuses core/registry.dispatch for every tool
call, so sub-agents share the exact same tools as Freya herself.
"""

import asyncio
import itertools
import threading
import time

from google import genai
from google.genai import types

from config import get_agent_api_key
from core import runtime
from core.registry import register, tool, dispatch as registry_dispatch, ToolContext, OBJ, P, STR
from core.execution import ExecutionError, Exhausted, bounded
from core.context_trim import TRIM_MARK, compact_results
from core.quota import describe_failure, estimate_tokens, generate, usage
from core.task_policy import TOOLS_FIRST

# Built-in agent specs (config `sub_agents.<type>` may override model/system/tools).
DEFAULT_AGENTS = {
    "researcher": {
        "model": "gemini-3.5-flash",
        "system": (
            "You are Freyja's research sub-agent. Investigate the task properly — do not answer "
            "from what you already know.\n"
            "For straightforward read-only research, use web_search and web_fetch first. Use the browser only when interaction or JavaScript is required. Browser capability: `browser_research` searches DuckDuckGo, "
            "opens the actual pages and reads them, then hands you the findings. `web_search` is the quick path for a single fact or "
            "to find candidate URLs; `browser_open` reads one specific page you already have a "
            "URL for. Use web_search first when the question is "
            "genuinely one line long.\n"
            "Corroborate anything important across two sources. If the browser is blocked, try web_search and web_fetch for the same authorized "
            "read-only research. A retailer name alone does not complete product comparison: "
            "report actual model/specification, price/currency, availability and source URL, "
            "or clearly state which requested facts could not be verified. "
            "Write a spoken-friendly briefing — facts first, sources named naturally, no fluff, no "
            "markdown."
        ),
        "tools": ["browser_research", "browser_open", "browser_task", "web_search", "web_fetch",
                  "get_world_news", "recall", "read_file", "read_document", "ocr_document", "find_on_pc", "list_dir", "search_files"],
    },
    "coder": {
        "model": "gemini-3.5-flash",
        "system": (
            "You are Freyja's coding sub-agent. Complete the engineering task end to end: read the "
            "relevant files, make the change, run code/tests to verify. Be precise. Finish with a "
            "one-paragraph plain-English summary of what you changed and whether it worked."
        ),
        "tools": ["read_file", "write_file", "edit_file", "run_code", "list_dir",
                  "search_files", "run_terminal_command"],
    },
    "operator": {
        "model": "gemini-3.5-flash",
        "system": (
            "You are Freyja's desktop-operator sub-agent. Drive the Windows GUI through the "
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

DEFAULT_AGENTS["cli"] = {
    "model": "gemini-3.5-flash",
    "system": "You are Freyja's local command-line agent. Complete authorized tasks using terminal commands, direct file readers and APIs. Inspect first, act, then verify actual exit status and artifacts. Follow the existing safety and approval gates. Do not use GUI or screenshots as a shortcut. Report missing CLI capabilities honestly.",
    "tools": ["run_terminal_command", "run_code", "read_file", "read_document", "ocr_document", "write_file", "edit_file", "find_on_pc", "list_dir", "search_files", "web_search", "web_fetch"],
}

MAX_STEPS = 8
_counter = itertools.count(1)
_jobs: dict[str, dict] = {}  # id -> {type, task, status, result, started}

# Token budget for every background ReAct loop (sub-agents and mission steps).
# Override any key under config `agent_budget`.
#
# Each step re-sends the system prompt, every tool declaration and the whole
# history, and Gemini's tokens-per-minute limit counts all of that as input,
# so a loop that keeps pasting 4,000-character tool results grows until it
# runs into the limit. Two rules keep it bounded:
#   - Past max_context_tokens, tool results older than the last
#     keep_recent_results are cut to a short head. Only our own tool output is
#     trimmed: the model's turns go back exactly as received, which stateless
#     function calling requires (thought signatures). They are trimmed in one
#     go, so the history keeps a stable prefix for implicit caching afterwards.
#   - Past max_tokens_per_task input tokens, or at the last step, the model is
#     told to answer with what it has, with tools switched off. A partial
#     answer is worth more than an exhausted budget and nothing to show.
#
# Defaults measured on a simulated 8-step research task with 4,000-character
# tool results: input drops ~17% (41k -> 34k tokens) and no single request
# grows past ~6k, where untrimmed ones reach ~9k; at 12 steps the saving is
# ~32% (87k -> 59k). Keeping the 3 newest results whole and 800 characters of
# older ones leaves the evidence a final answer needs.
AGENT_BUDGET = {
    "max_context_tokens": 6_000,
    "max_tokens_per_task": 150_000,
    "keep_recent_results": 3,
    "max_tool_result_chars": 4_000,
    "trimmed_result_chars": 800,
    # Thinking tokens are billed as output. "low" suits tool-driven steps;
    # raise it per agent type with sub_agents.<type>.thinking_level.
    "thinking_level": "low",
    "max_concurrent": 2,
}

_WRAP_UP = ("[BUDGET] You are out of steps or token budget for this task. Do not call any more "
            "tools. Answer now with what you have found or done, and say plainly what is still "
            "unfinished.")
_TRIM_MARK = TRIM_MARK
_compact = compact_results


def _budget(config: dict) -> dict:
    return {**AGENT_BUDGET, **((config or {}).get("agent_budget") or {})}


def _spec(agent_type: str, config: dict) -> dict:
    override = (config or {}).get("sub_agents", {}).get(agent_type, {})
    base = DEFAULT_AGENTS.get(agent_type, DEFAULT_AGENTS["researcher"]).copy()
    base.update({k: v for k, v in override.items() if v})
    return base


def _declarations(spec: dict, config: dict):
    """The FunctionDeclarations for this agent's allowed tools, pulled from the registry."""
    from core.registry import build_declarations
    available = build_declarations(config)
    allowed = set(spec.get("tools", []))
    decls = []
    for declaration in available:
        if declaration.name in allowed:
            decls.append(declaration)
    # Legacy terminal handler keeps its existing safety/approval dispatch path.
    from core.registry import _REGISTRY
    if "run_terminal_command" in allowed and "run_terminal_command" not in _REGISTRY:
        decls.append(types.FunctionDeclaration(name="run_terminal_command",
            description="Run a shell command through Freyja's safety and approval gate.",
            parameters=OBJ({"command": P(STR)}, ["command"])))
    # A name in an agent's tool list that the registry can't supply is silently
    # dropped, and the agent then fails at a task it was configured to do with
    # no clue why. Legacy tools declared only in model.py (run_terminal_command)
    # and handler-only overrides both land here. Say so once, loudly.
    missing = allowed - {d.name for d in decls}
    if missing:
        print(f"  [agents] tools not available from the registry, skipped: {sorted(missing)}")
    return decls


async def react_loop(system: str, task: str, tool_names: list[str], model: str,
                     config: dict, ctx: ToolContext, max_steps: int = MAX_STEPS,
                     on_tool=None, thinking_level: str | None = None) -> str:
    """Shared ReAct executor: a background Gemini text model calling registry
    tools until it answers in plain text. Used by quick sub-agents AND by each
    mission step (core/missions.py). `on_tool(name, args, result)` — optional
    async callback fired after every tool call (evidence collection, UI events).

    Token use is bounded by AGENT_BUDGET (see above).
    Raises on API errors — callers decide how to phrase failures.
    """
    if max_steps <= 0:
        raise Exhausted("Agent exhausted its step budget before completion")
    budget = _budget(config)
    level = thinking_level or budget.get("thinking_level")
    client = genai.Client(api_key=get_agent_api_key(), http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        decls = _declarations({"tools": tool_names}, config)
        allowed = {d.name for d in decls}
        cfg = types.GenerateContentConfig(
            system_instruction=system + "\n" + TOOLS_FIRST,
            tools=[types.Tool(function_declarations=decls)] if decls else None,
            temperature=0.4,
            thinking_config=types.ThinkingConfig(thinking_level=level) if level else None,
        )
        # Same tools stay declared (so the cached prefix is unchanged); the
        # model is just not allowed to call them.
        wrap_cfg = cfg.model_copy(update={"tool_config": types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="NONE"))}) if decls else cfg
        contents = [types.Content(role="user", parts=[types.Part(text=task)])]
        timeout = (config or {}).get("missions", {}).get("model_timeout_s", 90)
        result_chars = int(budget["max_tool_result_chars"])
        spent = 0          # input tokens used by this task so far
        last_prompt = 0    # exact input size of the previous request
        sent = 0           # how many contents that request carried

        for step in range(max_steps):
            # Size of the next request: the last exact count plus what was
            # added since, or a full estimate when there is no count to go on.
            if last_prompt:
                projected = last_prompt + estimate_tokens(contents[sent:])
            else:
                projected = estimate_tokens(contents, cfg)
            if projected > budget["max_context_tokens"]:
                if _compact(contents, int(budget["keep_recent_results"]),
                            int(budget["trimmed_result_chars"])):
                    last_prompt = 0
            wrap_up = step == max_steps - 1 or spent >= budget["max_tokens_per_task"]
            if wrap_up:
                contents[-1].parts = [*(contents[-1].parts or []), types.Part(text=_WRAP_UP)]

            sent = len(contents)
            try:
                resp = await bounded(generate(client, quota_config=config,
                    model=model, contents=contents, config=wrap_cfg if wrap_up else cfg
                ), timeout)
            except Exception as exc:
                # A model without thinking levels rejects the setting; drop it
                # once rather than failing the whole task.
                if not level or "thinking" not in str(exc).lower():
                    raise
                level = None
                cfg = cfg.model_copy(update={"thinking_config": None})
                wrap_cfg = wrap_cfg.model_copy(update={"thinking_config": None})
                resp = await bounded(generate(client, quota_config=config,
                    model=model, contents=contents, config=wrap_cfg if wrap_up else cfg
                ), timeout)
            prompt = getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", None)
            if isinstance(prompt, int):
                last_prompt = prompt
                spent += prompt
            else:
                last_prompt = 0
                spent += projected

            cand = (resp.candidates or [None])[0]
            if cand is None or cand.content is None:
                raise ExecutionError("Model returned no candidate")
            parts = cand.content.parts or []
            fcalls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not fcalls:
                if not resp.text or not resp.text.strip():
                    raise ExecutionError("Model returned no completion summary")
                return resp.text
            if wrap_up:
                break
            contents.append(cand.content)
            tool_parts = []
            for fc in fcalls:
                args = dict(fc.args or {})
                if fc.name not in allowed:
                    raise ExecutionError(f"Tool unavailable to this agent: {fc.name}")
                # Dispatch stays on THIS loop. It used to be marshalled onto the
                # live session's loop via `ctx.owner_loop`, which undid the
                # thread isolation below: the agent's thread only ever held the
                # Gemini calls, while every tool — browser, screen, file scan —
                # ran on the voice loop and the user could not talk to her.
                # The session-bound pieces (speech, dashboard events, approval
                # futures) marshal themselves now, in core/background.py.
                result = await bounded(registry_dispatch(fc.name, args, ctx),
                    (config or {}).get("missions", {}).get("tool_timeout_s", 180))
                if str(result).lower().startswith(("command failed", "command timed out", "tool error", "unknown tool", "mcp call failed")):
                    raise ExecutionError(f"{fc.name} failed; inspect tool output before retrying")
                if on_tool is not None:
                    try:
                        await on_tool(fc.name, args, str(result))
                    except Exception:
                        pass
                tool_parts.append(types.Part(function_response=types.FunctionResponse(
                    id=getattr(fc, "id", None), name=fc.name,
                    response={"result": str(result)[:result_chars]})))
            contents.append(types.Content(role="user", parts=tool_parts))
        raise Exhausted("Agent exhausted its step budget before completion")
    finally:
        close = getattr(client.aio, "aclose", None)
        if close is not None:
            await close()


def quota_hit(e: Exception) -> bool:
    text = str(e).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


def _emit_threadsafe(main_loop: asyncio.AbstractEventLoop, coro):
    """Marshal an async runtime call from the worker thread back onto the live
    session's loop. Fire-and-forget — the worker never blocks on the result.

    `main_loop` is kept for call-site compatibility; the destination is resolved
    centrally now so it stays correct across reconnects, when the live session
    gets a new loop but the agent thread is still holding the old one.
    """
    from core import background
    background.call_on_main(coro)


def _run_agent_thread(job_id: str, agent_type: str, task: str, config: dict,
                      main_loop: asyncio.AbstractEventLoop):
    """Run one sub-agent on its OWN thread with its OWN event loop.

    This used to be `asyncio.create_task(...)` on the live voice session's loop,
    which is why dispatching an agent made Freya's speech lag. Two things went
    wrong there:

      • Its ReAct loop awaits Gemini calls and dispatches tools on the same loop
        that schedules the mic/speaker coroutines, so any stall it hit was a
        stall the audio path shared.
      • Sync tool handlers run via `run_in_executor(None, ...)` — the default
        thread pool. A sub-agent doing screen captures or file scans would
        occupy those workers, and audio I/O queued behind them.

    Model.py now reserves a dedicated pool for audio, and this puts the agent's
    own work on a separate loop entirely: heavy background jobs and the realtime
    voice path no longer share a scheduler. Same isolation core/browser_agent.py
    already uses, and for exactly the same reason.
    """
    # Its own usage bucket: requests and tokens (nested browser calls included)
    # are counted per job, and max_requests_per_mission caps a runaway agent.
    config = {**(config or {}), "_quota_mission": job_id}
    ctx = ToolContext(config, session=None, source=f"agent:{job_id}")

    # Parallel agents share one per-minute quota; more at once only makes each
    # wait longer and raises the chance of a 429. Extra jobs queue here.
    slots = _slots(config)
    if not slots.acquire(blocking=False):
        _jobs[job_id]["status"] = "queued"
        _emit_threadsafe(main_loop, runtime.emit(
            "agent", {"id": job_id, "agent": agent_type, "task": task, "status": "queued"}))
        slots.acquire()
        _jobs[job_id]["status"] = "working"
        _emit_threadsafe(main_loop, runtime.emit(
            "agent", {"id": job_id, "agent": agent_type, "task": task, "status": "working"}))
    try:
        _run_agent(job_id, agent_type, task, config, ctx, main_loop)
    finally:
        slots.release()


_slot_lock = threading.Lock()
_slot_state: dict = {"size": None, "sem": None}


def _slots(config: dict) -> threading.Semaphore:
    size = max(1, int(_budget(config)["max_concurrent"]))
    with _slot_lock:
        if _slot_state["size"] != size:
            _slot_state.update(size=size, sem=threading.Semaphore(size))
        return _slot_state["sem"]


def _usage_line(stats: dict) -> str:
    if not stats.get("requests"):
        return ""
    line = f"{stats['requests']} request{'s' if stats['requests'] != 1 else ''}, {stats.get('input_tokens', 0):,} input tokens"
    if stats.get("cached_tokens"):
        line += f" ({stats['cached_tokens']:,} cached)"
    return line


def _run_agent(job_id: str, agent_type: str, task: str, config: dict, ctx: ToolContext,
               main_loop: asyncio.AbstractEventLoop):
    async def _do_run():
        spec = _spec(agent_type, config)

        async def on_tool(name, args, result):
            # Record the step on the job too, not just in the event — the
            # dashboard's /agents fetch (on load / reconnect) reads the table,
            # and without this a reconnecting client loses all step detail.
            job = _jobs.get(job_id)
            if job is not None:
                job["step"] = name
            _emit_threadsafe(main_loop, runtime.emit(
                "agent", {"id": job_id, "agent": agent_type, "task": task,
                          "step": name, "status": "working", "usage": usage(job_id)}))

        return await react_loop(spec["system"], task, spec.get("tools", []),
                                spec["model"], config, ctx, on_tool=on_tool,
                                thinking_level=spec.get("thinking_level"))

    try:
        final = asyncio.run(_do_run())
        status = "done"
    except Exception as e:
        status = getattr(e, "outcome", "failed")
        reason = describe_failure(e) if quota_hit(e) else None
        if reason:
            final = f"I couldn't finish: {reason}"
        else:
            final = f"My {agent_type} agent hit an error: {e}"

    stats = usage(job_id)
    _jobs[job_id].update(status=status, result=final, step=None, usage=stats)
    _emit_threadsafe(main_loop, runtime.emit(
        "agent", {"id": job_id, "agent": agent_type, "task": task,
                  "status": status, "result": str(final)[:400], "usage": stats}))
    _emit_threadsafe(main_loop, runtime.inject(
        f"Your {agent_type} agent finished the task '{task}'. Here's the result: {final}"))


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "dispatch_agent",
    "Delegate a multi-step task to a background sub-agent: cli (local commands/files, preferred over GUI), researcher (web research), coder "
    "(write/run code), operator (drive the GUI). Reports back out loud when done.",
    OBJ({"agent_type": P(STR, "cli, researcher, coder, or operator"),
         "task": P(STR, "The full task for the sub-agent to accomplish")},
        ["agent_type", "task"]),
)
async def dispatch_agent(args, ctx) -> str:
    agent_type = (args.get("agent_type") or "researcher").lower().strip()
    task = (args.get("task") or "").strip()
    if agent_type not in DEFAULT_AGENTS and agent_type not in (ctx.config or {}).get("sub_agents", {}):
        return f"Unknown agent type '{agent_type}'. Use cli, researcher, coder, or operator."
    if not task:
        return "Give the sub-agent a task to do."
    job_id = f"{agent_type[:3]}-{next(_counter)}"
    _jobs[job_id] = {"type": agent_type, "task": task, "status": "working",
                     "result": None, "started": time.time()}
    main_loop = asyncio.get_running_loop()
    threading.Thread(
        target=_run_agent_thread,
        args=(job_id, agent_type, task, ctx.config, main_loop),
        daemon=True, name=f"sub-agent-{job_id}",
    ).start()
    await ctx.emit("agent", {"id": job_id, "agent": agent_type, "status": "started", "task": task})
    return (f"Dispatched the {agent_type} agent (job {job_id}) on: {task}. "
            "It's working in the background — I'll tell you when it's done.")


@tool("check_agents", "Check the status of background sub-agents you've dispatched.", OBJ())
def check_agents(args, ctx) -> str:
    if not _jobs:
        return "No sub-agents have been dispatched yet."
    lines = []
    for jid, j in _jobs.items():
        age = int(time.time() - j["started"])
        spent = _usage_line(j.get("usage") or usage(jid))
        spent = f" [{spent}]" if spent else ""
        if j["status"] == "done":
            lines.append(f"{jid} ({j['type']}): done{spent} — {str(j['result'])[:160]}")
        elif j["status"] == "queued":
            lines.append(f"{jid} ({j['type']}): queued behind other agents ({age}s) on '{j['task'][:60]}'")
        elif j["status"] not in ("working",):
            lines.append(f"{jid} ({j['type']}): {j['status']}{spent} — {str(j['result'])[:160]}")
        else:
            lines.append(f"{jid} ({j['type']}): still working ({age}s){spent} on '{j['task'][:60]}'")
    return "\n".join(lines)
