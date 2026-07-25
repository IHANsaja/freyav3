"""
System / OS control suite — the foundational "agent" powers over the Windows desktop.

Gives Freya hands on the operating system itself: clipboard, the filesystem, window
management, media + volume, and power. Everything that touches files or closes windows is
flagged dangerous=True so it passes through core/safety.py first.

All third-party imports are local + guarded, so a missing optional package only disables
that one tool group rather than crashing the whole assistant.
"""

import os
import glob as _glob
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
    "Copy text onto the Windows clipboard so Ihan can paste it.",
    OBJ({"text": P(STR, "Text to place on the clipboard")}, ["text"]),
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
    OBJ({"path": P(STR, "Absolute path to the file")}, ["path"]),
)
def read_file(args, ctx) -> str:
    path = resolve_user_path(args.get("path", ""))
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
    OBJ({"path": P(STR, "Absolute path to write"),
         "content": P(STR, "Full text content to write")}, ["path", "content"]),
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


@tool(
    "search_files",
    "Search a directory tree for files matching a glob pattern (e.g. *.pdf, report*).",
    OBJ({"directory": P(STR, "Root directory to search"),
         "pattern": P(STR, "Glob pattern, e.g. *.png")}, ["directory", "pattern"]),
)
def search_files(args, ctx) -> str:
    directory = resolve_user_path(args.get("directory", "~"))
    pattern = args.get("pattern", "*")
    try:
        hits = _glob.glob(os.path.join(directory, "**", pattern), recursive=True)[:40]
        if not hits:
            return f"No files matching {pattern} under {directory}."
        return f"Found {len(hits)} match(es): " + "; ".join(hits)
    except Exception as e:
        return f"Search failed: {e}"


# ══════════════════════════════════════════════
#  WINDOW MANAGEMENT
# ══════════════════════════════════════════════
def _windows():
    import pygetwindow as gw
    return gw


@tool("list_windows", "List the titles of all open application windows.", OBJ())
def list_windows(args, ctx) -> str:
    try:
        titles = [t for t in _windows().getAllTitles() if t.strip()]
        if not titles:
            return "No open windows found."
        return "Open windows: " + "; ".join(titles[:40])
    except Exception as e:
        return f"Couldn't list windows: {e}"


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
