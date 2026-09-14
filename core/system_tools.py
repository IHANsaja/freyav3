"""
System / OS control suite — the foundational "agent" powers over the Windows desktop.

Gives Freya hands on the operating system itself: clipboard, the filesystem, window
management, media + volume, and power. Everything that touches files or closes windows is
flagged dangerous=True so it passes through core/safety.py first.

All third-party imports are local + guarded, so a missing optional package only disables
that one tool group rather than crashing the whole assistant.
"""

import os
import subprocess

from core.registry import register, tool, OBJ, P, STR, INT, BOOL
from core.user_paths import resolve_user_path

MAX_READ = 20_000  # chars — keep file reads digestible for a voice model


# ══════════════════════════════════════════════
#  CLIPBOARD
# ══════════════════════════════════════════════
@tool("clipboard_read", "Read the current text contents of the Windows clipboard.", OBJ())
def clipboard_read(args, ctx) -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        return f"Clipboard contains: {text[:MAX_READ]}" if text else "The clipboard is empty."
    except Exception as e:
        return f"Couldn't read clipboard: {e}"


@tool(
    "clipboard_write",
    "Copy text onto the Windows clipboard so the user can paste it.",
    OBJ({"text": P(STR)}, ["text"]),
)
def clipboard_write(args, ctx) -> str:
    try:
        import pyperclip
        pyperclip.copy(args.get("text", ""))
        return "Copied to your clipboard."
    except Exception as e:
        return f"Couldn't write clipboard: {e}"


# ══════════════════════════════════════════════
#  FILESYSTEM
# ══════════════════════════════════════════════
@tool(
    "read_file",
    "Read a text file from disk and return its contents.",
    OBJ({"path": P(STR)}, ["path"]),
)
def read_file(args, ctx) -> str:
    path = resolve_user_path(args.get("path", ""))
    if os.path.splitext(path)[1].lower() in (".pdf", ".docx"):
        from core.document_reader import read_document
        return read_document(args, ctx)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
        if len(data) > MAX_READ:
            return f"{data[:MAX_READ]}\n…(truncated, {len(data)} chars total)"
        return data or "(file is empty)"
    except Exception as e:
        return f"Couldn't read {path}: {e}"


@tool(
    "write_file",
    "Create or overwrite a text file with the given content.",
    OBJ({"path": P(STR),
         "content": P(STR)}, ["path", "content"]),
    dangerous=True,
)
def write_file(args, ctx) -> str:
    path = resolve_user_path(args.get("path", ""))
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(args.get("content", ""))
        return f"Wrote {len(args.get('content', ''))} chars to {path}."
    except Exception as e:
        return f"Couldn't write {path}: {e}"


@tool(
    "list_dir",
    "List the files and folders inside a directory.",
    OBJ({"path": P(STR, "Directory path (defaults to home)")}),
)
def list_dir(args, ctx) -> str:
    path = resolve_user_path(args.get("path") or "~")
    try:
        entries = sorted(os.listdir(path))
        if not entries:
            return f"{path} is empty."
        shown = entries[:60]
        tag = lambda e: e + ("/" if os.path.isdir(os.path.join(path, e)) else "")
        more = f" …and {len(entries) - 60} more" if len(entries) > 60 else ""
        return f"{path}: " + ", ".join(tag(e) for e in shown) + more
    except Exception as e:
        return f"Couldn't list {path}: {e}"


SEARCH_BUDGET_S = 20.0   # a voice model waiting longer than this has already lost
SEARCH_MAX_HITS = 40


@tool(
    "search_files",
    "Search a folder and everything under it for files matching a name pattern "
    "(e.g. *.pdf, report*, *invoice*). Use when he names the folder to look in. To find "
    "something anywhere on the PC without knowing the folder, use find_on_pc instead.",
    OBJ({"directory": P(STR),
         "pattern": P(STR, "Glob pattern, e.g. *.png")}, ["directory", "pattern"]),
)
def search_files(args, ctx) -> str:
    directory = resolve_user_path(args.get("directory", "~"))
    pattern = args.get("pattern", "*")
    if not os.path.isdir(directory):
        return f"There's no folder at {directory}."

    # os.walk rather than glob.glob(recursive=True): glob materialises the
    # ENTIRE match list before any slice, so a 40-hit cap saved the model's
    # context and nothing else — pointed at a drive it walked node_modules,
    # AppData and $Recycle.Bin for minutes before returning. This prunes and
    # stops on a clock.
    import fnmatch
    import time
    from core.machine_index import _SKIP_DIRS

    deadline = time.time() + SEARCH_BUDGET_S
    hits: list[str] = []
    ran_out = False
    try:
        for dirpath, dirs, files in os.walk(directory, onerror=lambda e: None):
            if time.time() > deadline:
                ran_out = True
                break
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for f in files:
                if fnmatch.fnmatch(f.lower(), pattern.lower()):
                    hits.append(os.path.join(dirpath, f))
                    if len(hits) >= SEARCH_MAX_HITS:
                        break
            if len(hits) >= SEARCH_MAX_HITS:
                break
    except Exception as e:
        return f"Search failed: {e}"

    if not hits:
        if ran_out:
            return (f"I searched {directory} for {SEARCH_BUDGET_S:.0f} seconds and found "
                    f"nothing matching {pattern} before I ran out of time. It might be "
                    f"deeper in — give me a narrower folder and I'll go again.")
        return f"No files matching {pattern} under {directory}."
    tail = " (there may be more — I stopped early)" if ran_out or \
        len(hits) >= SEARCH_MAX_HITS else ""
    return f"Found {len(hits)} match(es){tail}: " + "; ".join(hits)


# ══════════════════════════════════════════════
#  WINDOW MANAGEMENT
# ══════════════════════════════════════════════
def _windows():
    import pygetwindow as gw
    return gw


# Shell furniture that owns real top-level windows but is never what a person
# means by "what's open".
_SHELL_PROCS = {"explorer.exe", "textinputhost.exe", "applicationframehost.exe",
                "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe",
                "systemsettings.exe", "lockapp.exe"}

# Background noise in a full process list — hundreds of these exist and none of
# them answer "is X running?".
_NOISE_PROCS = {"svchost.exe", "conhost.exe", "dllhost.exe", "rundll32.exe",
                "csrss.exe", "wininit.exe", "services.exe", "lsass.exe", "smss.exe",
                "fontdrvhost.exe", "dwm.exe", "sihost.exe", "taskhostw.exe",
                "runtimebroker.exe", "wmiprvse.exe", "audiodg.exe", "spoolsv.exe",
                "registry", "memory compression", "system idle process", "system"}


def _visible_windows() -> list[tuple[str, str, bool]]:
    """(process_name, title, is_focused) for every real top-level window.

    pygetwindow's getAllTitles() is titles-only, which can't answer "what
    programs are open" — a title like "Untitled - Notepad" is a lucky case, and
    "Inbox (12)" tells you nothing. So enumerate properly and ask the OS which
    process owns each HWND. Guarded imports: no pywin32 disables this one tool.
    """
    import win32gui
    import win32process
    import psutil

    foreground = win32gui.GetForegroundWindow()
    out: list[tuple[str, str, bool]] = []

    def visit(hwnd, _extra):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return
        try:  # zero-size windows are invisible shells, not open programs
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right - left <= 1 or bottom - top <= 1:
                return
        except Exception:
            pass
        proc = ""
        try:
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid).name()
        except Exception:
            pass
        out.append((proc, title, hwnd == foreground))

    win32gui.EnumWindows(visit, None)
    return out


def _pretty(proc: str) -> str:
    """chrome.exe -> Chrome. Spoken aloud, so drop the extension."""
    return os.path.splitext(proc)[0].title() if proc else "something"


@tool(
    "list_windows",
    "What programs the user currently has open, and which one is in front. Use for "
    "'what have I got open', 'what programs are running', 'what's open right now', and "
    "'is X running'. Set include_background to also list programs running without a "
    "window (services, Docker, a game launcher sitting in the tray).",
    OBJ({"include_background": P(BOOL, "Also list processes that have no window "
                                       "(default false)")}),
)
def list_windows(args, ctx) -> str:
    try:
        windows = _visible_windows()
    except Exception as e:
        # pygetwindow fallback — titles only, but better than nothing.
        try:
            titles = [t for t in _windows().getAllTitles() if t.strip()]
            if not titles:
                return "No open windows found."
            return "Open windows: " + "; ".join(titles[:40])
        except Exception:
            return f"Couldn't list windows: {e}"

    # Group by program: eleven Chrome windows should read as one line.
    by_proc: dict[str, list[str]] = {}
    focused = ""
    for proc, title, is_focused in windows:
        if proc.lower() in _SHELL_PROCS and not is_focused:
            continue
        by_proc.setdefault(_pretty(proc), []).append(title)
        if is_focused:
            focused = _pretty(proc)

    lines = []
    for app in sorted(by_proc, key=lambda a: (a != focused, a.lower())):
        titles = by_proc[app]
        head = titles[0][:70]
        extra = f" (+{len(titles) - 1} more window{'s' if len(titles) > 2 else ''})" \
            if len(titles) > 1 else ""
        mark = " ← in front" if app == focused else ""
        lines.append(f"{app}: {head}{extra}{mark}")

    if not lines:
        return "Nothing's open right now apart from the desktop."
    msg = f"{len(by_proc)} program(s) open:\n" + "\n".join(lines)

    if args.get("include_background"):
        msg += "\n\nAlso running without a window: " + _background_procs(set(by_proc))
    return msg


def _background_procs(windowed: set[str]) -> str:
    """Named processes with no visible window, minus the OS's own furniture."""
    try:
        import psutil
    except Exception:
        return "(couldn't check — psutil unavailable)"
    names = set()
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").strip()
        if not name or name.lower() in _NOISE_PROCS:
            continue
        pretty = _pretty(name)
        if pretty not in windowed:
            names.add(pretty)
    if not names:
        return "nothing noteworthy."
    shown = sorted(names)[:60]
    more = f" …and {len(names) - len(shown)} more" if len(names) > len(shown) else ""
    return ", ".join(shown) + more + "."


def _find_window(title: str):
    wins = _windows().getWindowsWithTitle(title)
    return wins[0] if wins else None


@tool(
    "focus_window",
    "Bring an application window to the front by (partial) title.",
    OBJ({"title": P(STR, "Window title or part of it, e.g. Chrome")}, ["title"]),
)
def focus_window(args, ctx) -> str:
    try:
        w = _find_window(args.get("title", ""))
        if not w:
            return f"No window matching '{args.get('title')}'."
        if w.isMinimized:
            w.restore()
        w.activate()
        return f"Focused '{w.title}'."
    except Exception as e:
        return f"Couldn't focus window: {e}"


@tool("minimize_window", "Minimize a window by title.",
      OBJ({"title": P(STR, "Window title or part of it")}, ["title"]))
def minimize_window(args, ctx) -> str:
    try:
        w = _find_window(args.get("title", ""))
        if not w:
            return f"No window matching '{args.get('title')}'."
        w.minimize()
        return f"Minimized '{w.title}'."
    except Exception as e:
        return f"Couldn't minimize: {e}"


@tool("maximize_window", "Maximize a window by title.",
      OBJ({"title": P(STR, "Window title or part of it")}, ["title"]))
def maximize_window(args, ctx) -> str:
    try:
        w = _find_window(args.get("title", ""))
        if not w:
            return f"No window matching '{args.get('title')}'."
        w.maximize()
        return f"Maximized '{w.title}'."
    except Exception as e:
        return f"Couldn't maximize: {e}"


@tool("close_window", "Close a window by title.",
      OBJ({"title": P(STR, "Window title or part of it")}, ["title"]), dangerous=True)
def close_window(args, ctx) -> str:
    try:
        w = _find_window(args.get("title", ""))
        if not w:
            return f"No window matching '{args.get('title')}'."
        t = w.title
        w.close()
        return f"Closed '{t}'."
    except Exception as e:
        return f"Couldn't close: {e}"


# ══════════════════════════════════════════════
#  MEDIA + VOLUME
# ══════════════════════════════════════════════
@tool(
    "set_volume",
    "Set the master system volume to a percentage (0-100).",
    OBJ({"level": P(INT, "Volume percent 0-100")}, ["level"]),
)
def set_volume(args, ctx) -> str:
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        level = max(0, min(100, int(args.get("level", 50))))
        devices = AudioUtilities.GetSpeakers()
        iface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        vol = cast(iface, POINTER(IAudioEndpointVolume))
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level}%."
    except Exception as e:
        return f"Couldn't set volume: {e}"


@tool(
    "media_control",
    "Control media playback: play/pause, next, previous, or mute.",
    OBJ({"action": P(STR, "One of: play_pause, next, previous, mute")}, ["action"]),
)
def media_control(args, ctx) -> str:
    try:
        import pyautogui
        key = {
            "play_pause": "playpause", "play": "playpause", "pause": "playpause",
            "next": "nexttrack", "previous": "prevtrack", "prev": "prevtrack",
            "mute": "volumemute",
        }.get(args.get("action", "").lower())
        if not key:
            return "Unknown media action. Use play_pause, next, previous or mute."
        pyautogui.press(key)
        return f"Media: {args.get('action')}."
    except Exception as e:
        return f"Media control failed: {e}"


# ══════════════════════════════════════════════
#  POWER
# ══════════════════════════════════════════════
@tool("lock_screen", "Lock the Windows session immediately.", OBJ())
def lock_screen(args, ctx) -> str:
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return "Screen locked."
    except Exception as e:
        return f"Couldn't lock: {e}"


@tool("sleep_computer", "Put the computer to sleep.", OBJ(), dangerous=True)
def sleep_computer(args, ctx) -> str:
    try:
        subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
        return "Going to sleep."
    except Exception as e:
        return f"Couldn't sleep: {e}"
