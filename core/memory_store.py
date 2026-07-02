"""
Structured long-term memory — SQLite + FTS5 replacing the append-only markdown file.

Memory items are typed rows (preference / person / project / deadline / followup /
fact / session_summary) that are individually searchable, editable, and deactivatable —
so memory can be *managed*, not just accumulated. `compose_prompt()` renders the
system-prompt view: importance-ranked, kind-grouped, with upcoming deadlines surfaced.

All methods are synchronous (stdlib sqlite3); async callers run them in an executor,
the same pattern the Chroma RAG store already uses. The markdown file is imported
once on first run (see core/memory.py) and kept as a backup.
"""

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Literal, Optional

MEMORY_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "freya_memory.db")

Kind = Literal["preference", "person", "project", "deadline", "followup", "fact", "session_summary"]
KINDS: tuple[str, ...] = ("preference", "person", "project", "deadline", "followup", "fact", "session_summary")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 2,
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'conversation',
    active INTEGER NOT NULL DEFAULT 1
);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    subject, content, content='items', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, subject, content) VALUES (new.id, new.subject, new.content);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, subject, content) VALUES('delete', old.id, old.subject, old.content);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, subject, content) VALUES('delete', old.id, old.subject, old.content);
    INSERT INTO items_fts(rowid, subject, content) VALUES (new.id, new.subject, new.content);
END;
"""


@dataclass
class MemoryItem:
    id: int
    kind: str
    subject: str
    content: str
    importance: int
    due_at: Optional[str]
    created_at: str
    updated_at: str
    source: str
    active: bool

    def to_payload(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self, path: str = MEMORY_DB_PATH):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def _row(self, r: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=r["id"], kind=r["kind"], subject=r["subject"], content=r["content"],
            importance=r["importance"], due_at=r["due_at"], created_at=r["created_at"],
            updated_at=r["updated_at"], source=r["source"], active=bool(r["active"]),
        )

    # ── CRUD ───────────────────────────────────────────────────────────────

    def add(self, kind: str, subject: str, content: str, importance: int = 2,
            due_at: Optional[str] = None, source: str = "conversation") -> int:
        if kind not in KINDS:
            kind = "fact"
        importance = max(1, min(5, int(importance)))
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO items (kind, subject, content, importance, due_at, created_at, updated_at, source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (kind, subject.strip(), content.strip(), importance, due_at, now, now, source),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update(self, item_id: int, **fields) -> bool:
        allowed = {"kind", "subject", "content", "importance", "due_at", "active"}
        sets, values = [], []
        for key, value in fields.items():
            if key in allowed and value is not None:
                sets.append(f"{key} = ?")
                values.append(int(value) if key in ("importance", "active") else value)
        if not sets:
            return False
        sets.append("updated_at = ?")
        values.extend([_now(), item_id])
        with self._lock:
            cur = self._conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", values)
            self._conn.commit()
            return cur.rowcount > 0

    def deactivate(self, item_id: int) -> bool:
        return self.update(item_id, active=0)

    def get(self, item_id: int) -> Optional[MemoryItem]:
        r = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row(r) if r else None

    # ── Queries ────────────────────────────────────────────────────────────

    def search(self, query: str, kinds: Optional[list[str]] = None, limit: int = 20) -> list[MemoryItem]:
        query = (query or "").strip()
        if not query:
            return self.list(kinds=kinds, limit=limit)
        # FTS5 match, escaped as a phrase per token to tolerate punctuation
        fts = " ".join(f'"{t}"' for t in query.replace('"', " ").split())
        sql = ("SELECT items.* FROM items_fts JOIN items ON items.id = items_fts.rowid "
               "WHERE items_fts MATCH ? AND items.active = 1")
        args: list = [fts]
        if kinds:
            sql += f" AND items.kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        try:
            rows = self._conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            return []
        return [self._row(r) for r in rows]

    def list(self, kinds: Optional[list[str]] = None, limit: int = 200,
             include_inactive: bool = False) -> list[MemoryItem]:
        sql = "SELECT * FROM items"
        clauses, args = [], []
        if not include_inactive:
            clauses.append("active = 1")
        if kinds:
            clauses.append(f"kind IN ({','.join('?' * len(kinds))})")
            args.extend(kinds)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        args.append(limit)
        return [self._row(r) for r in self._conn.execute(sql, args).fetchall()]

    def due(self, before: Optional[datetime] = None) -> "list[MemoryItem]":
        """Deadline/followup items due before `before` (default: now)."""
        cutoff = (before or datetime.now()).isoformat(timespec="seconds")
        rows = self._conn.execute(
            "SELECT * FROM items WHERE active = 1 AND due_at IS NOT NULL AND due_at <= ? "
            "AND kind IN ('deadline','followup') ORDER BY due_at",
            (cutoff,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM items WHERE active = 1").fetchone()[0])

    # ── Rendered views ─────────────────────────────────────────────────────

    def compose_prompt(self, max_items: int = 60) -> str:
        """The system-prompt memory block: ranked facts, people, projects,
        preferences, upcoming deadlines, and recent session summaries."""
        if self.count() == 0:
            return ""
        sections: list[str] = []

        core_kinds = ("preference", "person", "project", "fact")
        items = self.list(kinds=list(core_kinds), limit=max_items)
        by_kind: dict[str, list[MemoryItem]] = {}
        for item in items:
            by_kind.setdefault(item.kind, []).append(item)
        titles = {"preference": "Preferences", "person": "People",
                  "project": "Projects", "fact": "Facts"}
        for kind in core_kinds:
            if by_kind.get(kind):
                lines = "\n".join(f"- {i.subject}: {i.content}" for i in by_kind[kind])
                sections.append(f"### {titles[kind]}\n{lines}")

        upcoming = self._conn.execute(
            "SELECT * FROM items WHERE active = 1 AND due_at IS NOT NULL "
            "AND kind IN ('deadline','followup') AND due_at >= ? ORDER BY due_at LIMIT 10",
            (_now(),),
        ).fetchall()
        if upcoming:
            lines = "\n".join(f"- {r['due_at']}: {r['subject']} — {r['content']}" for r in upcoming)
            sections.append(f"### Upcoming deadlines & follow-ups\n{lines}")

        summaries = self.list(kinds=["session_summary"], limit=3)
        if summaries:
            lines = "\n".join(f"- {i.created_at[:10]}: {i.content}" for i in summaries)
            sections.append(f"### Recent sessions\n{lines}")

        return "\n\n".join(sections)

    def export_markdown(self) -> str:
        """Legacy view for the old GET /memory endpoint / settings modal."""
        out = ["# Freya Memory (structured store — edit in the Memory panel)"]
        for kind in KINDS:
            items = self.list(kinds=[kind], limit=500)
            if items:
                out.append(f"\n## {kind}")
                for i in items:
                    due = f" (due {i.due_at})" if i.due_at else ""
                    out.append(f"- [{i.id}] {i.subject}: {i.content}{due}")
        return "\n".join(out)


_store: Optional[MemoryStore] = None


def get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
