"""
Activity overlay — a small pill at the top of the screen saying what Freya is
doing right now: "Thinking…", "Searching your PC for 'resume'", "Opening
report.pdf", "Waiting for your OK". It appears the moment she starts something,
stays for as long as the work lasts (with a running timer once it passes a few
seconds), and fades when she's done.

Why: 3.8 Live stays silent while a tool runs, so a 20-second disk search used
to look exactly like a hang. The dashboard showed tool results only after they
finished, and only if it was the window in front.

Constraints, because she drives the mouse and keyboard:
  * click-through (WS_EX_TRANSPARENT) — her clicks and his land on what's below;
  * never activates (WS_EX_NOACTIVATE) — press_key still types into the right window;
  * excluded from screen capture (WDA_EXCLUDEFROMCAPTURE) — capture_screen never
    shows her own status to herself.

Threading follows core/desktop_popup.py: one daemon thread owns its own Tk root
and is fed through a queue. Every public function here is safe from any thread
and a no-op when the overlay is disabled (config `activity_overlay.enabled`).
"""

import ctypes
import json
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

BG = "#0b0f0d"
BORDER = "#1c3a2e"
ACCENT = "#0f9c6e"
AMBER = "#e0a33a"
RED = "#e05a5a"
FLASH_S = 1.6             # how long a failed step stays on the pill
TEXT = "#e8f2ec"
MUTED = "#7d8c85"
KEY = "#010101"           # transparent colour for the window's corners

MAX_TEXT_PX = 560
LINGER_S = 0.9            # hold after the last activity so back-to-back tools don't flicker
THINK_AFTER_S = 0.8       # user stopped talking this long ago, no reply yet → "Thinking"
THINK_MAX_S = 25.0        # never show "Thinking" forever over an empty turn
SHOW_TIMER_AFTER_S = 3.0

_enabled = True
_manager = None
_lock = threading.Lock()


# ══════════════════════════════════════════════
#  WHAT TO SAY FOR EACH TOOL
# ══════════════════════════════════════════════
# Body language is not "doing something".
_SILENT_TOOLS = {"set_expression", "set_gesture", "set_idle_state", "trigger_emphasis",
                 "trigger_thinking", "trigger_listening", "animate_transition"}


def _q(value, limit: int = 40) -> str:
    text = " ".join(str(value or "").split())
    return f"“{text[:limit]}…”" if len(text) > limit else f"“{text}”"


def _base(path) -> str:
    path = str(path or "").rstrip("\\/")
    return os.path.basename(path) or path or "it"


_LABELS = {
    # finding things
    "find_on_pc": lambda a: f"Searching your PC for {_q(a.get('what'))}",
    "search_files": lambda a: f"Searching {_base(a.get('directory'))} for {_q(a.get('pattern'))}",
    "find_files_by": lambda a: f"Checking {'the biggest' if a.get('sort_by') == 'largest' else 'the newest'} files in {_base(a.get('directory'))}",
    "list_dir": lambda a: f"Looking inside {_base(a.get('path'))}",
    "get_user_folders": lambda a: "Finding your folders",
    "file_info": lambda a: f"Checking {_base(a.get('path'))}",
    "disk_usage": lambda a: f"Checking free space on {a.get('drive') or 'C:'}",
    "list_installed_apps": lambda a: "Checking your installed apps",
    "list_my_projects": lambda a: "Listing your projects",
    "pc_knowledge_status": lambda a: "Checking what I know about your PC",
    "refresh_pc_knowledge": lambda a: "Re-scanning your PC",
    "index_folder": lambda a: f"Learning the files in {_base(a.get('path'))}",
    # files
    "open_path": lambda a: f"Opening {_base(a.get('path'))}",
    "reveal_in_explorer": lambda a: f"Showing {_base(a.get('path'))} in Explorer",
    "read_file": lambda a: f"Reading {_base(a.get('path'))}",
    "read_document": lambda a: f"Reading {_base(a.get('path'))}",
    "ocr_document": lambda a: f"Reading the text in {_base(a.get('path'))}",
    "write_file": lambda a: f"Writing {_base(a.get('path'))}",
    "edit_file": lambda a: f"Editing {_base(a.get('path'))}",
    "create_folder": lambda a: f"Creating folder {_base(a.get('path'))}",
    "copy_item": lambda a: f"Copying {_base(a.get('source'))}",
    "move_item": lambda a: f"Moving {_base(a.get('source'))}",
    "delete_item": lambda a: f"Deleting {_base(a.get('path'))}",
    "zip_item": lambda a: f"Zipping {_base(a.get('source') or a.get('path'))}",
    "unzip_archive": lambda a: f"Unzipping {_base(a.get('path'))}",
    "organize_folder": lambda a: f"Tidying {_base(a.get('folder')) if a.get('folder') else 'your desktop'}",
    "undo_organize": lambda a: "Putting your files back",
    # apps & windows
    "open_app": lambda a: f"Opening {a.get('name') or 'the app'}",
    "close_app": lambda a: f"Closing {a.get('name') or 'the app'}",
    "open_project": lambda a: f"Opening project {a.get('name') or ''}".strip(),
    "focus_window": lambda a: f"Bringing {a.get('title') or 'the window'} to the front",
    "minimize_window": lambda a: f"Minimizing {a.get('title') or 'the window'}",
    "maximize_window": lambda a: f"Maximizing {a.get('title') or 'the window'}",
    "close_window": lambda a: f"Closing {a.get('title') or 'the window'}",
    "list_windows": lambda a: "Checking what's open",
    "get_active_window": lambda a: "Checking the window in front",
    # screen & input
    "capture_screen": lambda a: "Looking at your screen",
    "look_at_screen": lambda a: "Looking at your screen",
    "take_screenshot": lambda a: "Taking a screenshot",
    "read_screen_elements": lambda a: "Reading what's on screen",
    "find_element": lambda a: f"Finding {_q(a.get('name') or a.get('query') or a.get('text'))} on screen",
    "click_element": lambda a: "Clicking",
    "click_text": lambda a: f"Clicking {_q(a.get('text'))}",
    "control_element": lambda a: f"Using {_q(a.get('name') or a.get('element'))}",
    "press_key": lambda a: f"Pressing {a.get('key') or 'a key'}",
    "type_text": lambda a: "Typing",
    "watch_screen": lambda a: "Watching your screen",
    "stop_watching": lambda a: "Stopping the screen watch",
    "clipboard_read": lambda a: "Reading your clipboard",
    "clipboard_write": lambda a: "Copying to your clipboard",
    # system
    "set_volume": lambda a: (f"Setting volume to {a['level']}%" if a.get("level") is not None
                             else "Setting the volume"),
    "media_control": lambda a: f"Media: {str(a.get('action') or '').replace('_', ' ')}",
    "lock_screen": lambda a: "Locking your screen",
    "sleep_computer": lambda a: "Putting the PC to sleep",
    "shutdown_computer": lambda a: "Shutting down",
    "run_terminal_command": lambda a: f"Running {_q(a.get('command'), 48)}",
    "run_code": lambda a: "Running code",
    "pause_listening": lambda a: "Pausing listening",
    "switch_mode": lambda a: f"Switching to {str(a.get('mode') or '').replace('_', ' ')} mode",
    # web & news
    "web_search": lambda a: f"Searching the web for {_q(a.get('query'))}",
    "web_fetch": lambda a: "Reading a web page",
    "browser_open": lambda a: "Opening the browser",
    "browser_task": lambda a: f"Browsing: {_q(a.get('task'), 48)}",
    "browser_research": lambda a: f"Researching {_q(a.get('topic') or a.get('query') or a.get('task'), 44)}",
    "browser_status": lambda a: "Checking the browser",
    "get_news": lambda a: "Getting the news",
    "get_world_news": lambda a: "Getting world news",
    "get_weather": lambda a: f"Checking the weather{' in ' + a['city'] if a.get('city') else ''}",
    # memory & day
    "remember": lambda a: "Saving that to memory",
    "recall": lambda a: f"Remembering {_q(a.get('query'))}",
    "recall_conversation": lambda a: "Remembering our conversation",
    "list_memories": lambda a: "Going through my memories",
    "update_memory_item": lambda a: "Updating a memory",
    "forget": lambda a: "Forgetting that",
    "get_day_context": lambda a: "Checking your day",
    "note_day_context": lambda a: "Noting that for today",
    "rotate_day_context": lambda a: "Closing out the day",
    "schedule_task": lambda a: "Setting a reminder",
    "list_tasks": lambda a: "Checking your reminders",
    "cancel_task": lambda a: "Cancelling a reminder",
    "whats_coming_up": lambda a: "Checking what's coming up",
    # agents, missions, skills
    "start_mission": lambda a: f"Starting a mission: {_q(a.get('goal'), 44)}",
    "mission_status": lambda a: "Checking the mission",
    "cancel_mission": lambda a: "Cancelling the mission",
    "dispatch_agent": lambda a: f"Sending a {a.get('agent_type') or ''} agent: {_q(a.get('task'), 40)}",
    "check_agents": lambda a: "Checking on my agents",
    "use_skill": lambda a: f"Using skill {a.get('name') or a.get('skill') or ''}".strip(),
    "run_skill_script": lambda a: "Running a skill script",
    "list_skills": lambda a: "Checking my skills",
    "create_tool": lambda a: f"Building a new tool: {a.get('name') or ''}".strip(),
    "search_tools": lambda a: "Working out how to do that",
    "approve_action": lambda a: "Doing what you approved",
    "reject_action": lambda a: "Cancelling that",
    "list_pending_actions": lambda a: "Checking pending approvals",
    # show & avatar
    "show_image": lambda a: "Putting an image on screen",
    "show_info": lambda a: "Putting a card on screen",
    "dance_for_user": lambda a: "Dancing",
    # trading lab
    "open_trading_lab": lambda a: "Opening the Trading Lab",
    "analyze_chart": lambda a: "Analyzing the chart",
    "draw_on_chart": lambda a: "Drawing on the chart",
    "clear_my_drawings": lambda a: "Clearing my chart drawings",
    "paper_order": lambda a: f"Placing a paper {a.get('side') or ''} order".replace("  ", " "),
    "get_paper_portfolio": lambda a: "Checking your paper portfolio",
    "get_market_news": lambda a: "Getting market news",
    "review_trades": lambda a: "Reviewing your trades",
    "advance_replay": lambda a: "Advancing the replay",
    "record_trading_thesis": lambda a: "Saving your trading thesis",
}


def describe(name: str, args: dict | None) -> str | None:
    """A short present-tense sentence for a tool call, or None to show nothing."""
    args = dict(args or {})
    if name == "run_tool":
        name = str(args.get("name") or "")
        inner = args.get("arguments")
        if isinstance(inner, str):
            try:
                inner = json.loads(inner) if inner.strip() else {}
            except ValueError:
                inner = {}
        args = inner if isinstance(inner, dict) else {}
    if not name or name in _SILENT_TOOLS:
        return None
    try:
        label = _LABELS[name](args) if name in _LABELS else None
    except Exception:
        label = None
    return label or name.replace("_", " ").capitalize()


# ══════════════════════════════════════════════
#  PUBLIC API  (any thread; no-ops when disabled)
# ══════════════════════════════════════════════
def configure(config: dict | None):
    global _enabled
    _enabled = bool(((config or {}).get("activity_overlay") or {}).get("enabled", True))


def tool_started(call_id, name: str, args: dict | None):
    label = describe(name, args)
    _feed().tool_started(call_id, name, args, label)
    if label:
        _send({"op": "tool_start", "id": str(call_id or name), "label": label})


def tool_mode(call_id, mode: str):
    """The call moved to the background (outlived the talk-first window) or is queued."""
    _feed().tool_mode(call_id, mode)


def tool_outcome(call_id, status: str, detail: str = ""):
    """How a call ended — ok / error / timeout / resting — reported before tool_finished."""
    _feed().tool_outcome(call_id, status, detail)
    if status != "ok":
        _send({"op": "outcome", "id": str(call_id), "status": status})


def tool_finished(call_id, name: str = ""):
    _feed().tool_finished(call_id, name)
    _send({"op": "tool_end", "id": str(call_id or name)})


def heard():
    """The user is talking (a transcription fragment just arrived)."""
    _feed().heard()
    _send({"op": "heard"})


def responding():
    """The model produced output — speech, text or a call — so it isn't 'thinking'."""
    _feed().responding()
    _send({"op": "responding"})


def set_state(value: str):
    _feed().set_state(value)
    _send({"op": "state", "value": value})


def waiting_for_approval(action_id: str, summary: str):
    _feed().approval(action_id, summary)
    _send({"op": "approval", "id": action_id, "label": f"Waiting for your OK — {summary}"})


def approval_done(action_id: str):
    _feed().approval(action_id, None)
    _send({"op": "approval_end", "id": action_id})


def recovering(detail: str):
    """The live link is down and being re-established ('' when it's back)."""
    _feed().set_recovering(detail)
    _send({"op": "recovering", "label": detail})


def clear():
    _feed().clear()
    _send({"op": "clear"})


def _feed():
    from core.activity import feed
    return feed


def attach_to_bus():
    """Show approval waits (they come from the bus, not from a tool call)."""
    from core.events import bus

    async def _listener(event):
        if event.type != "approval":
            return
        p = event.payload or {}
        if p.get("event") == "requested":
            waiting_for_approval(p.get("id", ""), p.get("summary") or "a sensitive action")
        elif p.get("event") == "resolved":
            approval_done(p.get("id", ""))

    async def _health(event):
        # The live link being re-established is something she is "doing" too:
        # without this the pill vanished during a reconnect and she looked hung.
        if event.type != "health":
            return
        components = (event.payload or {}).get("components", [])
        live = next((c for c in components if c.get("name") == "live"), None)
        if live is None:
            return
        down = live.get("state") in ("recovering", "down")
        recovering((live.get("detail") or "Reconnecting") if down else "")

    detach = [bus.subscribe(_listener), bus.subscribe(_health)]
    return lambda: [d() for d in detach]


def _send(cmd: dict):
    if not _enabled:
        return
    try:
        _get().queue.put(cmd)
    except Exception as e:           # never let the overlay break a tool call
        print(f"  [activity] overlay unavailable: {e}")
        _disable()


def _disable():
    global _enabled
    _enabled = False


def _get():
    global _manager
    with _lock:
        if _manager is None:
            _manager = _Overlay()
        return _manager


# ══════════════════════════════════════════════
#  THE WINDOW  (tk thread only below this line)
# ══════════════════════════════════════════════
def _work_area():
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return None


def _make_passive(root):
    """Click-through, never focused, hidden from screenshots, off the taskbar."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x00000080, 0x08000000, 0x00000008
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                              | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        # WDA_EXCLUDEFROMCAPTURE (Windows 10 2004+); older builds just ignore it.
        # FREYA_OVERLAY_CAPTURABLE=1 keeps it in screenshots, for checking the look.
        if os.environ.get("FREYA_OVERLAY_CAPTURABLE") != "1":
            user32.SetWindowDisplayAffinity(hwnd, 0x11)
    except Exception:
        pass


def _show_without_focus(root):
    """Map the window without activating it (SW_SHOWNOACTIVATE), falling back
    to Tk's own deiconify where the Win32 call isn't available."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        user32.ShowWindow(hwnd, 4)          # SW_SHOWNOACTIVATE
        # HWND_TOPMOST, no move/size/activate
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    except Exception:
        root.deiconify()


class _Overlay:
    def __init__(self):
        self.queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error = None
        threading.Thread(target=self._run, daemon=True, name="freya-activity").start()
        self._ready.wait(timeout=4)
        if self._error:
            raise self._error

    # state (tk thread)
    tools: dict
    approvals: dict

    def _run(self):
        try:
            # Creating a Tk root makes it the foreground window even while
            # withdrawn. Remember who had focus and hand it straight back, or
            # the first activity would pull focus off the user's app — and off
            # the window press_key was about to type into.
            try:
                previous = ctypes.windll.user32.GetForegroundWindow()
            except Exception:
                previous = None
            root = self.root = tk.Tk()
            # Stay hidden until the no-activate style is on: Tk maps a new root
            # with a normal show, which took focus from the user's window.
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.0)
            root.configure(bg=KEY)
            root.attributes("-transparentcolor", KEY)
            self.canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
            self.canvas.pack(fill="both", expand=True)
            self.font = tkfont.Font(family="Segoe UI Semibold", size=11)
            self.small = tkfont.Font(family="Segoe UI", size=10)
            root.geometry("10x10+-100+-100")
            root.update_idletasks()
            _make_passive(root)
            _show_without_focus(root)
            if previous:
                try:
                    ctypes.windll.user32.SetForegroundWindow(previous)
                except Exception:
                    pass
        except Exception as e:
            self._error = e
            self._ready.set()
            return
        self.tools = {}           # id -> (label, started_at, step), insertion-ordered
        self.approvals = {}       # id -> label
        self.failed = {}          # id -> status, for tools that ended badly
        self.flash = None         # (text, until) — a failed step, shown briefly
        self.steps = 0            # tools in the current streak of work
        self.recovering = ""
        self.state = "idle"
        self.heard_at = 0.0       # last user transcription fragment
        self.thinking_since = 0.0
        self.shown = None         # (text, colour) currently drawn
        self.shown_since = 0.0
        self.alpha = 0.0
        self.last_busy = 0.0
        self.phase = 0
        self._ready.set()
        self._tick()
        root.mainloop()

    def _handle(self, cmd: dict):
        op = cmd.get("op")
        now = time.monotonic()
        if op == "tool_start":
            if not self.tools and now - self.last_busy > LINGER_S * 2:
                self.steps = 0        # a new streak of work starts counting again
            self.steps += 1
            self.tools[cmd["id"]] = (cmd["label"], now, self.steps)
            self.thinking_since = 0.0
        elif op == "outcome":
            self.failed[cmd["id"]] = cmd.get("status") or "error"
        elif op == "tool_end":
            entry = self.tools.pop(cmd["id"], None)
            status = self.failed.pop(cmd["id"], None)
            if entry and status:
                word = {"timeout": "timed out", "resting": "is resting"}.get(status, "failed")
                self.flash = (f"{entry[0]} — {word}, trying another way", now + FLASH_S)
        elif op == "recovering":
            self.recovering = cmd.get("label") or ""
        elif op == "approval":
            self.approvals[cmd["id"]] = cmd["label"]
        elif op == "approval_end":
            self.approvals.pop(cmd["id"], None)
        elif op == "heard":
            self.heard_at = now
            self.thinking_since = 0.0
        elif op == "responding":
            self.heard_at = 0.0
            self.thinking_since = 0.0
        elif op == "state":
            self.state = cmd.get("value") or "idle"
            if self.state in ("speaking", "idle", "interrupted"):
                self.heard_at = 0.0
                self.thinking_since = 0.0
            if self.state == "idle":
                self.tools.clear()
        elif op == "clear":
            self.tools.clear()
            self.approvals.clear()
            self.failed.clear()
            self.flash = None
            self.heard_at = self.thinking_since = 0.0

    def _wanted(self, now: float):
        """(text, colour, started_at) to show, or None."""
        if self.recovering:
            return self.recovering, AMBER, None
        if self.approvals:
            return list(self.approvals.values())[-1], AMBER, None
        if self.flash and now < self.flash[1]:
            return self.flash[0], RED, None
        self.flash = None
        if self.tools:
            label, started, step = list(self.tools.values())[-1]
            more = len(self.tools) - 1
            prefix = f"Step {step} · " if step > 1 else ""
            return (prefix + label + (f"  (+{more} more)" if more else ""), ACCENT, started)
        # User finished a sentence and nothing has come back yet → thinking.
        if self.heard_at and now - self.heard_at > THINK_AFTER_S:
            if not self.thinking_since:
                self.thinking_since = self.heard_at + THINK_AFTER_S
            if now - self.thinking_since < THINK_MAX_S:
                return "Thinking", ACCENT, self.thinking_since
            self.heard_at = self.thinking_since = 0.0
        if self.state == "thinking":
            return "Thinking", ACCENT, None
        return None

    def _tick(self):
        try:
            while True:
                self._handle(self.queue.get_nowait())
        except queue.Empty:
            pass
        except Exception as e:
            print(f"  [activity] {e}")

        now = time.monotonic()
        want = self._wanted(now)
        if want:
            self.last_busy = now
        visible = want is not None or (self.shown and now - self.last_busy < LINGER_S)
        if want:
            self._draw(*want, now)
        elif visible and self.shown:
            self._draw(self.shown[0], self.shown[1], None, now)

        target = 0.94 if visible else 0.0
        step = 0.16 if visible else 0.08
        if abs(self.alpha - target) > 0.01:
            self.alpha += step if target > self.alpha else -step
            self.alpha = max(0.0, min(0.94, self.alpha))
            try:
                self.root.attributes("-alpha", self.alpha)
            except Exception:
                pass
        if not visible and self.alpha <= 0.01:
            self.shown = None
        self.phase += 1
        self.root.after(60, self._tick)

    def _draw(self, text: str, colour: str, started, now: float):
        timer = ""
        if started and now - started >= SHOW_TIMER_AFTER_S:
            timer = f"{int(now - started)}s"
        if self.font.measure(text) > MAX_TEXT_PX:
            while text and self.font.measure(text + "…") > MAX_TEXT_PX:
                text = text[:-1]
            text += "…"
        dots = "" if timer or colour in (AMBER, RED) else "." * (1 + (self.phase // 6) % 3)
        text_w = self.font.measure(text + "...")
        timer_w = self.small.measure(timer) + 12 if timer else 0
        h, pad, dot = 34, 16, 10
        w = pad + dot + 10 + text_w + timer_w + pad

        area = _work_area()
        left, top, right = (area[0], area[1], area[2]) if area else (0, 0, self.root.winfo_screenwidth())
        x = left + (right - left - w) // 2
        self.root.geometry(f"{w}x{h}+{x}+{top + 12}")

        c = self.canvas
        c.delete("all")
        r = h // 2
        for fill, inset in ((BORDER, 0), (BG, 1)):
            c.create_oval(inset, inset, h - inset, h - inset, fill=fill, outline=fill)
            c.create_oval(w - h + inset, inset, w - inset, h - inset, fill=fill, outline=fill)
            c.create_rectangle(r, inset, w - r, h - inset, fill=fill, outline=fill)
        # pulsing status dot
        pulse = 2 + (self.phase % 16) / 8 if (self.phase % 16) < 8 else 4 - (self.phase % 16) / 8
        cx, cy = pad + dot // 2, h // 2
        c.create_oval(cx - dot / 2 - pulse, cy - dot / 2 - pulse, cx + dot / 2 + pulse,
                      cy + dot / 2 + pulse, fill="", outline=colour, width=1)
        c.create_oval(cx - dot / 2, cy - dot / 2, cx + dot / 2, cy + dot / 2, fill=colour, outline=colour)
        tx = pad + dot + 10
        c.create_text(tx, cy, text=text + dots, fill=TEXT, font=self.font, anchor="w")
        if timer:
            c.create_text(w - pad, cy, text=timer, fill=MUTED, font=self.small, anchor="e")
        self.shown = (text, colour)
