"""
Day context — what today is *about*, and the rotation that closes it out.

Freya's memory was two extremes: a long-term store of durable facts, and a live
session that forgets everything the moment it ends. Nothing held the middle
ground — "what has been going on today" — so she could recite your job title but
had no idea you'd spent the morning on the memory refactor, and every new day
started identical to the last.

This module keeps a **rolling day context**:

  • a logical day (`day_start_hour`, default 04:00 — a 1am session still belongs
    to the previous day, which is how people actually experience "today")
  • per-day events: what was worked on, missions, reminders, approvals, notes
  • per-day activity totals: where the hours actually went, per app
  • carry-over: the unfinished threads inherited from yesterday

At the day boundary the context **rotates**: the open day is closed and
summarized (one cheap text-model call, deterministic fallback if unavailable),
its unfinished threads become tomorrow's carry-over, and a fresh day opens
seeded with them. `compose_prompt()` renders yesterday's summary + today so far
into the system prompt, so every session — and every session rotation — starts
knowing what day it is and what it has been about.

Storage lives in the same SQLite file as the memory store, in its own tables.
"""

import asyncio
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, date as _date, timedelta

DAY_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "freya_memory.db")

# Event kinds recorded against a day. `activity` is aggregated separately.
EVENT_KINDS = ("focus", "conversation", "mission", "reminder", "approval",
               "suggestion", "agent", "note")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS days (
    date        TEXT PRIMARY KEY,
    opened_at   TEXT NOT NULL,
    closed_at   TEXT,
    summary     TEXT NOT NULL DEFAULT '',
    carry_over  TEXT NOT NULL DEFAULT '[]',
    highlights  TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS day_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    date    TEXT NOT NULL,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS day_events_date ON day_events(date, id);
CREATE TABLE IF NOT EXISTS day_activity (
    date       TEXT NOT NULL,
    app        TEXT NOT NULL,
    seconds    INTEGER NOT NULL DEFAULT 0,
    last_title TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (date, app)
);
"""

_MAX_EVENTS_IN_PROMPT = 12
_MAX_APPS_IN_PROMPT = 5
_MIN_ACTIVITY_S = 45          # spans shorter than this are noise, not context
_ROTATION_TICK_S = 60.0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _part_of_day(hour: int) -> str:
    if hour < 5:
        return "the small hours"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


def _human_duration(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _pretty_date(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        return day
    return d.strftime("%A, %-d %B %Y") if os.name != "nt" else d.strftime("%A, %#d %B %Y")


class DayContext:
    """The store. One row per logical day, plus its events and activity totals."""

    def __init__(self, path: str = DAY_DB_PATH, day_start_hour: int = 4):
        self.path = os.path.abspath(path)
        self.day_start_hour = int(day_start_hour)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── Logical day ────────────────────────────────────────────────────────

    def logical_date(self, when: datetime | None = None) -> str:
        """The day a moment belongs to. Before `day_start_hour` it's still yesterday."""
        when = when or datetime.now()
        if when.hour < self.day_start_hour:
            when = when - timedelta(days=1)
        return when.strftime("%Y-%m-%d")

    def open_day(self, day: str | None = None) -> str:
        """Ensure a row exists for `day` (default: today) and return it."""
        day = day or self.logical_date()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO days (date, opened_at) VALUES (?, ?)", (day, _now()))
            self._conn.commit()
        return day

    def unclosed_days(self, before: str | None = None) -> list[str]:
        """Days still open, oldest first. `before` excludes today (and later).

        Plural on purpose: if Freya was off for a long weekend, three days are
        waiting to be closed and each deserves its own summary rather than being
        silently merged into one.
        """
        sql = "SELECT date FROM days WHERE closed_at IS NULL"
        args: list = []
        if before:
            sql += " AND date < ?"
            args.append(before)
        sql += " ORDER BY date"
        return [r["date"] for r in self._conn.execute(sql, args).fetchall()]

    def current_open_day(self) -> str | None:
        """The most recent day that has not been closed by a rotation yet."""
        r = self._conn.execute(
            "SELECT date FROM days WHERE closed_at IS NULL ORDER BY date DESC LIMIT 1").fetchone()
        return r["date"] if r else None

    def get_day(self, day: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM days WHERE date = ?", (day,)).fetchone()
        return dict(r) if r else None

    # ── Recording ──────────────────────────────────────────────────────────

    def note(self, kind: str, text: str, subject: str = "", day: str | None = None) -> None:
        """Record one thing that happened today. Cheap and synchronous."""
        text = (text or "").strip()
        if not text:
            return
        if kind not in EVENT_KINDS:
            kind = "note"
        day = self.open_day(day)
        with self._lock:
            # Don't record the same line twice in a row (repeat injects, retries).
            last = self._conn.execute(
                "SELECT text FROM day_events WHERE date = ? ORDER BY id DESC LIMIT 1", (day,)
            ).fetchone()
            if last and last["text"] == text[:400]:
                return
            self._conn.execute(
                "INSERT INTO day_events (date, ts, kind, subject, text) VALUES (?,?,?,?,?)",
                (day, _now(), kind, subject.strip()[:80], text[:400]),
            )
            self._conn.commit()

    def note_activity(self, app: str, title: str, seconds: float) -> None:
        """Accumulate a finished focus span into today's per-app totals."""
        if not app or seconds < _MIN_ACTIVITY_S:
            return
        day = self.open_day()
        with self._lock:
            self._conn.execute(
                "INSERT INTO day_activity (date, app, seconds, last_title, updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(date, app) DO UPDATE SET "
                "seconds = seconds + excluded.seconds, last_title = excluded.last_title, "
                "updated_at = excluded.updated_at",
                (day, app, int(seconds), (title or "")[:120], _now()),
            )
            self._conn.commit()

    # ── Reading ────────────────────────────────────────────────────────────

    def events(self, day: str, limit: int = 200, kinds: list[str] | None = None) -> list[dict]:
        sql = "SELECT * FROM day_events WHERE date = ?"
        args: list = [day]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [dict(r) for r in reversed(rows)]

    def activity(self, day: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT app, seconds, last_title FROM day_activity WHERE date = ? "
            "ORDER BY seconds DESC LIMIT ?", (day, limit)).fetchall()
        return [dict(r) for r in rows]

    def recent_days(self, limit: int = 7) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM days ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def carry_over(self, day: str) -> list[str]:
        row = self.get_day(day)
        if not row:
            return []
        try:
            return [str(x) for x in json.loads(row["carry_over"] or "[]")]
        except (ValueError, TypeError):
            return []

    # ── Rendered views ─────────────────────────────────────────────────────

    def render_day(self, day: str, heading: str | None = None) -> str:
        """A readable digest of one day — used for both the prompt and tools."""
        row = self.get_day(day)
        if row is None:
            return ""
        lines = [heading or f"### {_pretty_date(day)}"]

        if row["summary"]:
            lines.append(row["summary"])

        acts = self.activity(day, limit=_MAX_APPS_IN_PROMPT)
        if acts:
            spent = "; ".join(f"{a['app']} {_human_duration(a['seconds'])}" for a in acts)
            lines.append(f"Where the time went: {spent}")

        evs = self.events(day, limit=_MAX_EVENTS_IN_PROMPT)
        if evs:
            lines.append("What happened:")
            for e in evs:
                stamp = e["ts"][11:16]
                subject = f"{e['subject']}: " if e["subject"] else ""
                lines.append(f"- {stamp} [{e['kind']}] {subject}{e['text']}")

        pending = self.carry_over(day)
        if pending:
            lines.append("Still open:")
            lines.extend(f"- {p}" for p in pending)

        return "\n".join(lines) if len(lines) > 1 else ""

    def compose_prompt(self) -> str:
        """The day-context block injected into the system prompt."""
        today = self.open_day()
        now = datetime.now()
        header = (f"### Today — {_pretty_date(today)}, {now.strftime('%H:%M')} "
                  f"({_part_of_day(now.hour)})")

        block = self.render_day(today, heading=header)
        if not block:
            block = header + "\nNothing recorded yet today — this day is a blank page."

        parts = [
            "This is your rolling day context. It rotates at "
            f"{self.day_start_hour:02d}:00 each day: today's context is summarized and "
            "closed, anything unfinished carries into the next day. Use it to talk about "
            "today and yesterday concretely — reference it naturally, never recite it. "
            "Record anything that matters with `note_day_context`, and look further back "
            "with `get_day_context`.",
            block,
        ]

        previous = self._conn.execute(
            "SELECT * FROM days WHERE date < ? AND (summary != '' OR closed_at IS NOT NULL) "
            "ORDER BY date DESC LIMIT 1", (today,)).fetchone()
        if previous:
            prev = dict(previous)
            prev_lines = [f"### Previously — {_pretty_date(prev['date'])}"]
            if prev["summary"]:
                prev_lines.append(prev["summary"])
            else:
                digest = self.render_day(prev["date"], heading="")
                if digest:
                    prev_lines.append(digest.strip())
            if len(prev_lines) > 1:
                parts.append("\n".join(prev_lines))

        return "\n\n".join(parts)

    # ── Rotation ───────────────────────────────────────────────────────────

    def _fallback_summary(self, day: str) -> tuple[str, list[str]]:
        """Deterministic close-out when the summarizer model isn't available."""
        acts = self.activity(day, limit=4)
        evs = self.events(day, limit=40)
        bits = []
        if acts:
            total = sum(a["seconds"] for a in acts)
            bits.append(f"About {_human_duration(total)} at the machine, mostly "
                        + ", ".join(a["app"] for a in acts[:3]) + ".")
        kinds: dict[str, int] = {}
        for e in evs:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        if kinds:
            bits.append("Recorded: " + ", ".join(f"{n} {k}" for k, n in kinds.items()) + ".")
        if not bits:
            bits.append("A quiet day — nothing was recorded.")
        # Unfinished threads: notes explicitly marked open stay open.
        pending = [e["text"] for e in evs
                   if e["kind"] == "note" and e["subject"].lower() in ("open", "todo", "pending")]
        return " ".join(bits), pending

    async def _summarize(self, day: str, api_key: str | None
                         ) -> tuple[str, list[str], list[str], bool]:
        """(summary, carry_over, highlights, from_model) for a day being closed.

        `from_model` is False when the deterministic fallback wrote the text.
        Those close-outs are bookkeeping, not memory, and must not be archived
        into the long-term store — see rotate().
        """
        evs = self.events(day, limit=120)
        acts = self.activity(day, limit=10)
        if not evs and not acts:
            return "", [], [], False

        fallback_summary, fallback_carry = self._fallback_summary(day)
        if not api_key:
            return fallback_summary, fallback_carry, [], False

        timeline = "\n".join(
            f"{e['ts'][11:16]} [{e['kind']}] {e['subject']+': ' if e['subject'] else ''}{e['text']}"
            for e in evs) or "(no events)"
        spent = "\n".join(f"{a['app']}: {_human_duration(a['seconds'])} (last: {a['last_title']})"
                          for a in acts) or "(no activity tracked)"

        prompt = (
            f"Close out {_pretty_date(day)} for a personal assistant's day context.\n\n"
            "Write a short factual summary of what the day was about (2-4 sentences, "
            "second person, no fluff), then list any threads that are clearly UNFINISHED "
            "and should carry into the next day, and the day's few genuine highlights.\n"
            "Only use what is below. Do not invent tasks. If nothing is unfinished, "
            "return an empty list.\n\n"
            f"TIME SPENT:\n{spent}\n\nTIMELINE:\n{timeline}"
        )

        try:
            from google import genai
            from google.genai import types

            schema = types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "summary": types.Schema(type=types.Type.STRING),
                    "carry_over": types.Schema(type=types.Type.ARRAY,
                                               items=types.Schema(type=types.Type.STRING)),
                    "highlights": types.Schema(type=types.Type.ARRAY,
                                               items=types.Schema(type=types.Type.STRING)),
                },
                required=["summary", "carry_over", "highlights"],
            )
            client = genai.Client(api_key=api_key)
            resp = await client.aio.models.generate_content(
                model="gemini-flash-lite-latest",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_schema=schema),
            )
            data = json.loads(resp.text or "{}")
            summary = str(data.get("summary", "")).strip() or fallback_summary
            carry = [str(c).strip() for c in data.get("carry_over", []) if str(c).strip()][:8]
            highs = [str(h).strip() for h in data.get("highlights", []) if str(h).strip()][:6]
            return summary, carry, highs, True
        except Exception as e:
            print(f"  [day] summarizer unavailable ({e}); using deterministic close-out.")
            return fallback_summary, fallback_carry, [], False

    async def rotate(self, api_key: str | None = None, day: str | None = None) -> dict | None:
        """Close one day and start the next. Returns the closed day, or None.

        Idempotent: with no `day`, only days *before* today are eligible, so
        calling this repeatedly during a day does nothing. Pass `day` to force a
        close-out (the `rotate_day_context` tool).
        """
        today = self.logical_date()
        closing = day
        if closing is None:
            pending = self.unclosed_days(before=today)
            if not pending:
                self.open_day(today)
                return None
            closing = pending[0]

        summary, carry, highs, from_model = await self._summarize(closing, api_key)
        with self._lock:
            self._conn.execute(
                "UPDATE days SET closed_at = ?, summary = ?, carry_over = ?, highlights = ? "
                "WHERE date = ?",
                (_now(), summary, json.dumps(carry), json.dumps(highs), closing),
            )
            self._conn.commit()

        # Open the new day seeded with whatever is still unfinished.
        self.open_day(today)
        if carry:
            with self._lock:
                self._conn.execute("UPDATE days SET carry_over = ? WHERE date = ?",
                                   (json.dumps(carry), today))
                self._conn.commit()

        # Keep the long-term store in sync — but only for days that were
        # actually about something. Archiving every close-out meant rows like
        # "Recorded: 1 note." accumulating forever in long-term memory, each one
        # paying rent in the system prompt and telling her nothing.
        if summary and from_model:
            try:
                from core.memory_store import get_store
                get_store().add(kind="session_summary", subject=closing, content=summary,
                                importance=1, source="day_rotation")
            except Exception as e:
                print(f"  [day] could not archive summary to memory store: {e}")

        print(f"  [day] rotated {closing} -> {today}"
              + (f" ({len(carry)} carried over)" if carry else ""))
        return {"date": closing, "summary": summary, "carry_over": carry, "highlights": highs}

    def prune(self, keep_days: int = 60) -> int:
        """Drop raw events/activity older than `keep_days`. Summaries are kept."""
        cutoff = (_date.today() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        with self._lock:
            cur = self._conn.execute("DELETE FROM day_events WHERE date < ?", (cutoff,))
            self._conn.execute("DELETE FROM day_activity WHERE date < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount


_ctx: DayContext | None = None


def get_day_context() -> DayContext:
    global _ctx
    if _ctx is None:
        _ctx = DayContext()
    return _ctx


def note(kind: str, text: str, subject: str = "") -> None:
    """Module-level shorthand — safe to call from anywhere, never raises."""
    try:
        get_day_context().note(kind, text, subject)
    except Exception as e:
        print(f"  [day] note failed: {e}")


def note_activity(app: str, title: str, seconds: float) -> None:
    try:
        get_day_context().note_activity(app, title, seconds)
    except Exception as e:
        print(f"  [day] activity note failed: {e}")


def compose_prompt() -> str:
    try:
        return get_day_context().compose_prompt()
    except Exception as e:
        print(f"  [day] prompt build failed: {e}")
        return ""


# ══════════════════════════════════════════════
#  ROTATOR — the background clock
# ══════════════════════════════════════════════
class DayRotator:
    """Watches the clock and rotates the day context when it turns over.

    Mirrors Scheduler/ContextTracker: attached to the live session, detached on
    stop. It also subscribes to the event bus once, so missions, reminders and
    approvals land in the day's timeline without every module having to know
    this module exists.
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._config: dict = {}
        self._unsubscribe = None
        self._last_seen_day: str | None = None
        self._approval_summaries: dict[str, str] = {}

    def _cfg(self) -> dict:
        return ((self._config or {}).get("context", {}) or {}).get("day", {}) or {}

    def attach(self, config: dict):
        self._config = config or {}
        ctx = get_day_context()
        ctx.day_start_hour = int(self._cfg().get("day_start_hour", ctx.day_start_hour))
        self._subscribe()
        if self._task and not self._task.done():
            return
        # Don't open today here: any day left unclosed (Freya was off overnight,
        # or all weekend) must be rotated first, and the first tick does that.
        self._task = asyncio.create_task(self._loop())
        print(f"  [day] context attached ({ctx.logical_date()}).")

    def detach(self):
        if self._task:
            self._task.cancel()
            self._task = None
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    # ── Bus → day timeline ─────────────────────────────────────────────────

    def _subscribe(self):
        if self._unsubscribe:
            return
        from core.events import bus

        async def listener(event):
            try:
                self._record_event(event.type, event.payload or {})
            except Exception:
                pass

        self._unsubscribe = bus.subscribe(listener)

    def _record_event(self, etype: str, payload: dict):
        """Map a bus event onto the day timeline.

        Only outcomes are recorded, never progress chatter: a day is made of the
        things that finished, not of every step that ticked.
        """
        ctx = get_day_context()

        if etype == "mission":
            mission = payload.get("mission") or {}
            status = mission.get("status", "")
            goal = mission.get("goal", "")
            if goal and status in ("completed", "failed", "cancelled"):
                report = (mission.get("report") or "").strip()
                line = f"mission {status}: {goal}" + (f" — {report}" if report else "")
                ctx.note("mission", line)

        elif etype == "schedule":
            action = payload.get("action") or ""
            if action and payload.get("status") == "fired":
                ctx.note("reminder", str(action))

        elif etype == "approval":
            # 'resolved' carries only an id, so the summary is remembered from
            # the matching 'requested' event.
            if payload.get("event") == "requested" and payload.get("id"):
                self._approval_summaries[str(payload["id"])] = str(payload.get("summary", ""))
            elif payload.get("event") == "resolved":
                summary = self._approval_summaries.pop(str(payload.get("id")), "")
                if summary:
                    verb = "approved" if payload.get("approved") else "declined"
                    ctx.note("approval", f"{verb}: {summary}")

        elif etype == "suggestion":
            if payload.get("event") == "resolved" and payload.get("text"):
                ctx.note("suggestion", str(payload["text"]))

        elif etype == "agent":
            if payload.get("status") in ("done", "completed"):
                what = payload.get("task") or payload.get("result") or ""
                if what:
                    ctx.note("agent", f"{payload.get('agent', 'sub-agent')} finished: {what}")

    # ── The clock ──────────────────────────────────────────────────────────

    async def _loop(self):
        try:
            await self.tick()   # catch up on anything left open while she was off
            while True:
                await asyncio.sleep(_ROTATION_TICK_S)
                await self.tick()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [day] rotator error: {e}")

    async def tick(self):
        ctx = get_day_context()
        today = ctx.logical_date()
        if not ctx.unclosed_days(before=today):
            if self._last_seen_day != today:
                self._last_seen_day = today
                ctx.open_day(today)
            return

        api_key = None
        try:
            from config import get_agent_api_key
            api_key = get_agent_api_key()
        except Exception:
            pass

        # Close every stale day in order; `closed` ends up being the most recent.
        closed = None
        while ctx.unclosed_days(before=today):
            result = await ctx.rotate(api_key)
            if result is None:
                break
            closed = result
        self._last_seen_day = today
        ctx.prune(int(self._cfg().get("keep_raw_days", 60)))

        from core import runtime
        await runtime.emit("day", {"event": "rotated", "date": today,
                                   "closed": (closed or {}).get("date"),
                                   "summary": (closed or {}).get("summary", ""),
                                   "carryOver": (closed or {}).get("carry_over", [])})
        if closed:
            carry = closed.get("carry_over") or []
            pending = ("Still open: " + "; ".join(carry)) if carry else "Nothing was left open."
            await runtime.inject(
                f"[NEW DAY — it is now {_pretty_date(today)}. Yesterday: "
                f"{closed.get('summary', '')} {pending} "
                "Only mention this if it fits the conversation; a short natural line, "
                "not a briefing.]",
                priority="low",
            )


rotator = DayRotator()


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
from core.registry import tool, OBJ, P, STR  # noqa: E402  (registry imports config at load)


@tool(
    "note_day_context",
    "Record something into today's context — what he's working on, a decision, something that "
    "happened. For durable facts use `remember`. Tag it open/todo and it carries into tomorrow.",
    OBJ({
        "text": P(STR, "What happened, one sentence"),
        "subject": P(STR, "Optional tag — a project name, or 'open'/'todo' if unfinished"),
    }, required=["text"]),
)
async def note_day_context(args, ctx) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        return "Nothing to note."
    subject = str(args.get("subject", "")).strip()
    get_day_context().note("note", text, subject)
    return f"[SILENT] Noted in today's context: {text[:120]}"


@tool(
    "get_day_context",
    "Read a day's context — today, 'yesterday', or YYYY-MM-DD. Use for what he did, what he was "
    "working on, or where his time went.",
    OBJ({"day": P(STR, "'today', 'yesterday', or a YYYY-MM-DD date")}),
)
async def get_day_context_tool(args, ctx) -> str:
    store = get_day_context()
    raw = str(args.get("day", "today")).strip().lower() or "today"
    if raw in ("today", ""):
        day = store.logical_date()
    elif raw == "yesterday":
        day = (datetime.strptime(store.logical_date(), "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        try:
            day = datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return f"'{raw}' isn't a date I can read. Use today, yesterday, or YYYY-MM-DD."

    rendered = store.render_day(day)
    if not rendered:
        return f"Nothing recorded for {_pretty_date(day)}."
    return rendered


@tool(
    "rotate_day_context",
    "Manually close out the current day context and start the next one. Only for when the "
    "user explicitly asks to wrap up the day — it normally happens on its own.",
)
async def rotate_day_context(args, ctx) -> str:
    store = get_day_context()
    api_key = None
    try:
        from config import get_agent_api_key
        api_key = get_agent_api_key()
    except Exception:
        pass
    closed = await store.rotate(api_key, day=store.current_open_day())
    if not closed:
        return "There was no open day to close."
    carry = closed.get("carry_over") or []
    tail = f" Carried over: {'; '.join(carry)}." if carry else ""
    return f"Closed {closed['date']}. {closed.get('summary', '')}{tail}"
