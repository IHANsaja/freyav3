"""
Memory tools — Freya's voice-level interface to the structured memory store.

`remember` writes typed items during conversation (not just at session end), and
mirrors them into the Chroma vector store so semantic `recall` finds them too.
Everything runs in an executor because MemoryStore is synchronous sqlite.
"""

import asyncio

from core.memory_store import get_store, KINDS
from core.registry import tool, OBJ, P, STR, INT

_USER_KINDS = [k for k in KINDS if k != "session_summary"]


async def _run(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def _notify(ctx, kinds: list[str]):
    await ctx.emit("memory_changed", {"kinds": kinds})


def _mirror_to_rag(item_id: int, subject: str, content: str):
    """Best-effort upsert into the Chroma collection so `recall` sees it."""
    try:
        from core.rag_memory import upsert_memory_item
        upsert_memory_item(f"sqlite:{item_id}", f"{subject}: {content}")
    except Exception:
        pass  # RAG disabled or unavailable — FTS search still works


@tool(
    "remember",
    "Save something important to your long-term memory the moment you learn it: a "
    "preference, a person and their role, an ongoing project, a deadline or follow-up "
    f"(include due_at), or a notable fact. Kinds: {', '.join(_USER_KINDS)}.",
    OBJ({
        "kind": P(STR, f"One of: {', '.join(_USER_KINDS)}"),
        "subject": P(STR, "Short subject — a name, project, or topic"),
        "content": P(STR, "The thing to remember, one clear sentence"),
        "importance": P(INT, "1 (minor) to 5 (critical), default 3"),
        "due_at": P(STR, "ISO datetime like 2026-07-04T15:00 — only for deadline/followup"),
    }, ["kind", "subject", "content"]),
)
async def remember(args, ctx) -> str:
    store = get_store()
    kind = str(args.get("kind", "fact")).lower().strip()
    if kind not in _USER_KINDS:
        kind = "fact"
    subject = str(args.get("subject", "General")).strip()
    content = str(args.get("content", "")).strip()
    if not content:
        return "Give me something to remember."
    item_id = await _run(
        store.add, kind, subject, content,
        int(args.get("importance", 3) or 3), args.get("due_at") or None, "voice",
    )
    await _run(_mirror_to_rag, item_id, subject, content)
    await _notify(ctx, [kind])
    return f"Remembered ({kind} #{item_id}): {subject} — {content}"


@tool(
    "list_memories",
    "List what you remember, optionally filtered by kind "
    f"({', '.join(_USER_KINDS)}) or a search query.",
    OBJ({
        "kind": P(STR, "Optional kind filter"),
        "query": P(STR, "Optional search text"),
    }),
)
async def list_memories(args, ctx) -> str:
    store = get_store()
    kinds = [args["kind"]] if args.get("kind") in KINDS else None
    query = str(args.get("query", "")).strip()
    items = await _run(store.search, query, kinds, 15) if query else await _run(store.list, kinds, 15)
    if not items:
        return "Nothing stored for that yet."
    return "\n".join(
        f"#{i.id} [{i.kind}] {i.subject}: {i.content}" + (f" (due {i.due_at})" if i.due_at else "")
        for i in items
    )


@tool(
    "update_memory_item",
    "Correct or update a stored memory by its id (get ids from list_memories).",
    OBJ({
        "memory_id": P(INT, "The item id"),
        "content": P(STR, "New content"),
        "subject": P(STR, "New subject"),
        "importance": P(INT, "New importance 1-5"),
        "due_at": P(STR, "New ISO due datetime, for deadlines/followups"),
    }, ["memory_id"]),
)
async def update_memory_item(args, ctx) -> str:
    store = get_store()
    item_id = int(args.get("memory_id", 0))
    ok = await _run(
        store.update, item_id,
        content=args.get("content"), subject=args.get("subject"),
        importance=args.get("importance"), due_at=args.get("due_at"),
    )
    if not ok:
        return f"No memory #{item_id} found (or nothing to change)."
    item = await _run(store.get, item_id)
    if item:
        await _run(_mirror_to_rag, item.id, item.subject, item.content)
    await _notify(ctx, [item.kind if item else "fact"])
    return f"Updated memory #{item_id}."


@tool(
    "forget",
    "Deactivate a stored memory by id when Ihan says it's wrong or no longer relevant. "
    "It's hidden, not destroyed.",
    OBJ({"memory_id": P(INT, "The item id to forget")}, ["memory_id"]),
)
async def forget(args, ctx) -> str:
    store = get_store()
    item_id = int(args.get("memory_id", 0))
    ok = await _run(store.deactivate, item_id)
    if ok:
        await _notify(ctx, ["fact"])
    return f"Forgotten memory #{item_id}." if ok else f"No memory #{item_id} found."


@tool(
    "whats_coming_up",
    "List upcoming deadlines and follow-ups from memory (next 14 days).",
)
async def whats_coming_up(args, ctx) -> str:
    from datetime import datetime, timedelta
    store = get_store()
    items = await _run(store.due, datetime.now() + timedelta(days=14))
    if not items:
        return "Nothing due in the next two weeks."
    return "\n".join(f"{i.due_at}: {i.subject} — {i.content}" for i in items)
