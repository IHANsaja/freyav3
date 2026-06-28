"""
Safety gate — a single chokepoint every *dangerous* tool passes through before it runs.

Freya can now write files, run code, control the OS and spawn agents. That power needs a
guardrail. Tools registered with `dangerous=True` are checked here first. The gate:

  • refuses outright-destructive shell/file patterns (rm -rf, format, mkfs, fork bombs…)
  • blocks writes/deletes outside an allow-listed set of roots (config: safety.allowed_roots)
  • can be tightened/loosened from config (`safety` block); sensible defaults if absent.

Returns (allowed: bool, message: str). When blocked, `message` is what Freya tells the user.
"""

import os

# Patterns that are never allowed in a shell command, regardless of config.
_HARD_BLOCK = [
    "rm -rf", "rm -fr", ":(){", "mkfs", "format ", "del /f", "del /q",
    "rmdir /s", "format c:", "diskpart", "> /dev/sda", "dd if=", "shutdown -r",
]


def _cfg(config: dict) -> dict:
    return (config or {}).get("safety", {}) or {}


def _allowed_roots(config: dict) -> list[str]:
    roots = _cfg(config).get("allowed_roots")
    if roots:
        return [os.path.abspath(os.path.expanduser(r)) for r in roots]
    # Default: the user's home + the Freya project dir.
    home = os.path.expanduser("~")
    project = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return [os.path.abspath(home), project]


def path_is_allowed(path: str, config: dict) -> bool:
    """True if `path` sits inside one of the allow-listed roots."""
    try:
        target = os.path.abspath(os.path.expanduser(path))
    except Exception:
        return False
    for root in _allowed_roots(config):
        try:
            if os.path.commonpath([target, root]) == root:
                return True
        except ValueError:
            continue  # different drive on Windows
    return False


def check_command(command: str) -> tuple[bool, str]:
    low = (command or "").lower()
    for bad in _HARD_BLOCK:
        if bad in low:
            return False, f"I won't run that — it contains a destructive pattern ({bad.strip()})."
    return True, ""


def guard(tool_name: str, args: dict, config: dict) -> tuple[bool, str]:
    """Main entry point used by the registry for tools flagged dangerous."""
    if _cfg(config).get("unrestricted"):
        return True, ""  # user opted out of the gate entirely

    # Shell / code execution
    cmd = args.get("command") or args.get("code") or ""
    if cmd:
        ok, msg = check_command(str(cmd))
        if not ok:
            return ok, msg

    # File-touching tools must stay inside allowed roots
    if tool_name in ("write_file", "edit_file", "delete_file", "create_tool"):
        path = args.get("path") or args.get("file_path") or ""
        if path and not path_is_allowed(str(path), config):
            return False, (
                f"For safety I can only modify files inside your home folder or the Freya "
                f"project. '{path}' is outside that. Add it to safety.allowed_roots to permit it."
            )

    return True, ""
