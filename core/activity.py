"""
Activity feed — a structured, live account of what Freya is doing, for the dashboard.

The desktop pill (core/activity_overlay.py) shows one line. The dashboard has
room for the whole picture, so this module keeps it as data and publishes an
`activity` event whenever it changes:

    phase      idle | listening | hearing | thinking | speaking | working |
               approval | recovering — the one word that describes her now
    label      the sentence for that phase ("Searching your PC for “resume”")
    tools      every call in flight: name, plain-English label, category,
               start time, and whether it runs in the background or is queued
    recent     the last finished calls with outcome (ok / error / timeout /
               resting) and duration — the tool-usage history
    stats      calls, failures and total tool time this session

It is fed by the same hooks as the pill (activity_overlay forwards every call
here), so the two can never disagree. Everything is safe from any thread;
publishing hops to the server loop through the event bus.
"""

from __future__ import annotations

import threading
import time
from collections import deque

# What kind of work a tool is, for the icon beside it. Unknown tools are "other".
CATEGORIES: dict[str, set[str]] = {
    "search": {"find_on_pc", "search_files", "find_files_by", "list_dir", "get_user_folders",
               "file_info", "disk_usage", "list_installed_apps", "list_my_projects",
               "pc_knowledge_status", "refresh_pc_knowledge", "index_folder", "search_tools"},
    "file": {"open_path", "reveal_in_explorer", "read_file", "read_document", "ocr_document",
             "write_file", "edit_file", "create_folder", "copy_item", "move_item", "delete_item",
             "zip_item", "unzip_archive", "organize_folder", "undo_organize"},
    "app": {"open_app", "close_app", "open_project", "focus_window", "minimize_window",
            "maximize_window", "close_window", "list_windows", "get_active_window"},
    "screen": {"capture_screen", "look_at_screen", "take_screenshot", "read_screen_elements",
               "find_element", "click_element", "click_text", "control_element", "press_key",
               "type_text", "watch_screen", "stop_watching", "clipboard_read", "clipboard_write"},
    "system": {"set_volume", "media_control", "lock_screen", "sleep_computer", "shutdown_computer",
               "run_terminal_command", "run_code", "pause_listening", "switch_mode"},
    "web": {"web_search", "web_fetch", "browser_open", "browser_task", "browser_research",
            "browser_status", "get_news", "get_world_news", "get_weather"},
    "memory": {"remember", "recall", "recall_conversation", "list_memories", "update_memory_item",
               "forget", "get_day_context", "note_day_context", "rotate_day_context",
               "schedule_task", "list_tasks", "cancel_task", "whats_coming_up"},
    "agent": {"start_mission", "mission_status", "cancel_mission", "dispatch_agent", "check_agents",
              "use_skill", "run_skill_script", "list_skills", "create_tool", "approve_action",
              "reject_action", "list_pending_actions"},
    "trading": {"open_trading_lab", "analyze_chart", "draw_on_chart", "clear_my_drawings",
                "paper_order", "get_paper_portfolio", "get_market_news", "review_trades",
                "advance_replay", "record_trading_thesis"},
    "display": {"show_image", "show_info", "dance_for_user"},
}
_CATEGORY_OF = {tool: cat for cat, tools in CATEGORIES.items() for tool in tools}

RECENT_MAX = 12
PHASE_LABELS = {
    "idle": "Standing by",
    "listening": "Listening",
    "hearing": "Hearing you",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "recovering": "Reconnecting",
}


def category(name: str) -> str:
    if name.startswith("mcp_") or name.startswith("mcp__"):
        return "agent"
    return _CATEGORY_OF.get(name, "other")


def _inner(name: str, args: dict | None) -> tuple[str, dict]:
    """run_tool(name=X, arguments=…) is X as far as anyone watching is concerned."""
    args = dict(args or {})
    if name != "run_tool":
        return name, args
    import json
    inner = args.get("arguments")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner) if inner.strip() else {}
        except ValueError:
            inner = {}
    return str(args.get("name") or name), inner if isinstance(inner, dict) else {}


class ActivityFeed:
    def __init__(self, publish=None):
        self._lock = threading.Lock()
        self._publish_fn = publish
        self.reset()

    # ── state ──
    def reset(self):
        with self._lock:
            self.state = "idle"             # session state from the model loop
            self.tools: dict[str, dict] = {}
            self.approvals: dict[str, str] = {}
            self.outcomes: dict[str, tuple[str, str]] = {}
            self.recent: deque = deque(maxlen=RECENT_MAX)
            self.heard_at = 0.0
            self.recovering = ""
            self.stats = {"calls": 0, "failures": 0, "tool_ms": 0}
            self._last_sent = None

    # ── feed (any thread) ──
    def tool_started(self, call_id, name: str, args: dict | None, label: str | None):
        if not label:
            return                          # body language: not "doing something"
        tool, _ = _inner(name, args)
        with self._lock:
            self.tools[str(call_id or name)] = {
                "id": str(call_id or name), "name": tool, "label": label,
                "category": category(tool), "startedAt": time.time(), "mode": "foreground",
            }
            self.stats["calls"] += 1
            self.heard_at = 0.0
        self._emit()

    def tool_mode(self, call_id, mode: str):
        """'background' once a tool outlives the talk-first window, 'queued' while waiting."""
        with self._lock:
            entry = self.tools.get(str(call_id))
            if entry is None or entry["mode"] == mode:
                return
            entry["mode"] = mode
        self._emit()

    def tool_outcome(self, call_id, status: str, detail: str = ""):
        with self._lock:
            self.outcomes[str(call_id)] = (status, detail[:160])

    def tool_finished(self, call_id, name: str = ""):
        key = str(call_id or name)
        with self._lock:
            entry = self.tools.pop(key, None)
            status, detail = self.outcomes.pop(key, ("ok", ""))
            if entry is None:
                return
            ms = int((time.time() - entry["startedAt"]) * 1000)
            self.stats["tool_ms"] += ms
            if status != "ok":
                self.stats["failures"] += 1
            self.recent.appendleft({**entry, "status": status, "detail": detail,
                                    "ms": ms, "endedAt": time.time()})
        self._emit()

    def heard(self):
        with self._lock:
            first = not self.heard_at
            self.heard_at = time.time()
        if first:
            self._emit()

    def responding(self):
        with self._lock:
            was = self.heard_at
            self.heard_at = 0.0
        if was:
            self._emit()

    def set_state(self, value: str):
        with self._lock:
            self.state = value or "idle"
            if self.state in ("speaking", "idle", "interrupted"):
                self.heard_at = 0.0
            if self.state == "idle":
                self.tools.clear()
                self.approvals.clear()
        self._emit()

    def approval(self, action_id: str, summary: str | None):
        with self._lock:
            if summary is None:
                self.approvals.pop(action_id, None)
            else:
                self.approvals[action_id] = summary
        self._emit()

    def set_recovering(self, detail: str):
        with self._lock:
            if self.recovering == detail:
                return
            self.recovering = detail
        self._emit()

    def clear(self):
        with self._lock:
            self.tools.clear()
            self.approvals.clear()
            self.outcomes.clear()
            self.heard_at = 0.0
        self._emit()

    # ── view ──
    def snapshot(self) -> dict:
        with self._lock:
            tools = list(self.tools.values())
            if self.recovering:
                phase, label = "recovering", self.recovering
            elif self.approvals:
                phase, label = "approval", f"Waiting for your OK — {list(self.approvals.values())[-1]}"
            elif tools:
                phase, label = "working", tools[-1]["label"]
            elif self.heard_at:
                # The dashboard turns "hearing" into "thinking" once he has
                # paused (heardAt is the last fragment) — no timer needed here.
                phase, label = "hearing", PHASE_LABELS["hearing"]
            elif self.state == "thinking":
                phase, label = "thinking", PHASE_LABELS["thinking"]
            elif self.state == "speaking":
                phase, label = "speaking", PHASE_LABELS["speaking"]
            elif self.state in ("listening", "interrupted"):
                phase, label = "listening", PHASE_LABELS["listening"]
            else:
                phase, label = "idle", PHASE_LABELS["idle"]
            return {
                "phase": phase,
                "label": label,
                "state": self.state,
                "heardAt": self.heard_at or None,
                "tools": tools,
                "approvals": [{"id": k, "summary": v} for k, v in self.approvals.items()],
                "recent": list(self.recent),
                "stats": dict(self.stats),
                "ts": time.time(),
            }

    def _emit(self):
        snap = self.snapshot()
        # Only publish real changes: heard() fires on every transcription
        # fragment and set_state on every playback chunk boundary.
        fingerprint = (snap["phase"], snap["label"], snap["state"], bool(snap["heardAt"]),
                       tuple((t["id"], t["mode"]) for t in snap["tools"]),
                       tuple(a["id"] for a in snap["approvals"]),
                       tuple(r["id"] for r in snap["recent"]))
        with self._lock:
            if fingerprint == self._last_sent:
                return
            self._last_sent = fingerprint
        publish = self._publish_fn or _bus_publish
        try:
            publish(snap)
        except Exception as exc:
            print(f"  [activity] publish failed: {exc}")


def _bus_publish(snap: dict):
    from core.events import bus
    bus.publish_soon("activity", snap)


feed = ActivityFeed()
