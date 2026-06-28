"""
MCP client — Freya speaks the Model Context Protocol, so she can use ANY MCP server.

Configure servers under `mcp_servers` in freya_config.json (filesystem, github, brave-search,
fetch, your own…). On session start this manager launches each enabled server over stdio,
discovers its tools via `list_tools`, converts their JSON schemas into Gemini
FunctionDeclarations namespaced as `mcp__<server>__<tool>`, and routes calls back through
`call_tool`. To Gemini they look exactly like Freya's native tools.

Stability note: each connection is held open inside ONE dedicated asyncio task (see `_serve`).
Entering/closing the stdio context in the same task keeps anyio's cancel scopes happy, while
`call_tool` from other tasks works because ClientSession runs its own receive loop.
"""

import asyncio
from contextlib import AsyncExitStack

from google.genai import types

_TYPE_MAP = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
    "array": types.Type.ARRAY,
    "object": types.Type.OBJECT,
}


def _json_schema_to_gemini(schema: dict) -> types.Schema:
    """Best-effort JSON-Schema → google-genai Schema. Falls back to a permissive object."""
    if not isinstance(schema, dict):
        return types.Schema(type=types.Type.OBJECT)
    jtype = schema.get("type", "object")
    if isinstance(jtype, list):  # e.g. ["string","null"]
        jtype = next((t for t in jtype if t != "null"), "string")
    gtype = _TYPE_MAP.get(jtype, types.Type.STRING)
    kwargs = {"type": gtype}
    if schema.get("description"):
        kwargs["description"] = schema["description"][:1000]
    if schema.get("enum"):
        kwargs["enum"] = [str(e) for e in schema["enum"]]
    if gtype == types.Type.OBJECT:
        props = schema.get("properties", {}) or {}
        kwargs["properties"] = {k: _json_schema_to_gemini(v) for k, v in props.items()}
        if schema.get("required"):
            kwargs["required"] = list(schema["required"])
    if gtype == types.Type.ARRAY and schema.get("items"):
        kwargs["items"] = _json_schema_to_gemini(schema["items"])
    try:
        return types.Schema(**kwargs)
    except Exception:
        return types.Schema(type=types.Type.OBJECT)


def _extract_text(result) -> str:
    """Pull readable text out of an MCP CallToolResult."""
    try:
        chunks = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", None)
            if text:
                chunks.append(text)
            elif getattr(item, "type", "") == "resource":
                chunks.append(str(getattr(item, "resource", "")))
        out = "\n".join(chunks).strip()
        if getattr(result, "isError", False):
            return f"(MCP tool error) {out}"
        return out or "(MCP tool returned no text)"
    except Exception as e:
        return f"(couldn't parse MCP result: {e})"


class MCPManager:
    def __init__(self):
        self.sessions = {}          # server_name -> ClientSession
        self.tools = {}             # mcp__server__tool -> {server, tool, schema, desc}
        self._serve_task = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._started = False

    async def start(self, config: dict):
        if self._started:
            return
        servers = (config or {}).get("mcp_servers", {}) or {}
        active = {n: s for n, s in servers.items() if s.get("enabled")}
        if not active:
            return
        self._started = True
        self._ready.clear()
        self._stop.clear()
        self._serve_task = asyncio.create_task(self._serve(active))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        except asyncio.TimeoutError:
            print("  [MCP] timed out waiting for servers to initialize.")

    async def _serve(self, active: dict):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as e:
            print(f"  [MCP] python 'mcp' package missing: {e}")
            self._ready.set()
            return
        async with AsyncExitStack() as stack:
            for name, spec in active.items():
                try:
                    params = StdioServerParameters(
                        command=spec["command"],
                        args=spec.get("args", []),
                        env=spec.get("env") or None,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self.sessions[name] = session
                    listing = await session.list_tools()
                    for t in listing.tools:
                        full = f"mcp__{name}__{t.name}"
                        self.tools[full] = {
                            "server": name, "tool": t.name,
                            "schema": t.inputSchema or {"type": "object"},
                            "desc": (t.description or t.name)[:1000],
                        }
                    print(f"  [MCP] '{name}' up with {len(listing.tools)} tools.")
                except Exception as e:
                    print(f"  [MCP] failed to start '{name}': {e}")
            self._ready.set()
            await self._stop.wait()  # hold all connections open until stop()

    def get_declarations(self):
        decls = []
        for full, info in self.tools.items():
            try:
                decls.append(types.FunctionDeclaration(
                    name=full,
                    description=f"[MCP:{info['server']}] {info['desc']}",
                    parameters=_json_schema_to_gemini(info["schema"]),
                ))
            except Exception:
                continue
        return decls

    async def call(self, full_name: str, args: dict) -> str:
        info = self.tools.get(full_name)
        if not info:
            return f"Unknown MCP tool: {full_name}"
        session = self.sessions.get(info["server"])
        if session is None:
            return f"MCP server '{info['server']}' is not connected."
        try:
            result = await session.call_tool(info["tool"], args or {})
            return _extract_text(result)
        except Exception as e:
            return f"MCP call to {full_name} failed: {e}"

    async def stop(self):
        if not self._started:
            return
        self._stop.set()
        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=10)
            except Exception:
                self._serve_task.cancel()
        self.sessions.clear()
        self.tools.clear()
        self._started = False


# Singleton used by the registry + model.py lifecycle.
mcp_manager = MCPManager()
