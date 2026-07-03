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
import re

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
    """True if `path` sits inside one of the allow-listed roots.

    Comparison is case-INSENSITIVE via os.path.normcase. Windows filesystems
    resolve paths case-insensitively (open() on a mismatched-case path still
    hits the same real file), but Gemini routinely generates the user's name
    in natural title case ("Ihan Hansaja") rather than however the actual
    Windows account folder happens to be cased ("IHAN HANSAJA") — a naive
    case-sensitive compare here would then hard-block access to a folder
    (like the user's own Desktop) that Windows would happily write to and
    that may even be explicitly listed in safety.allowed_roots.
    """
    try:
        target = os.path.normcase(os.path.abspath(os.path.expanduser(path)))
    except Exception:
        return False
    for root in _allowed_roots(config):
        root_norm = os.path.normcase(root)
        try:
            if os.path.commonpath([target, root_norm]) == root_norm:
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


# ══════════════════════════════════════════════════════════════════════════
#  Approval rules — which actions must pause for Ihan's explicit yes.
#
#  Distinct from `guard` above: guard *blocks* the outright destructive, this
#  decides what is allowed but sensitive enough to need a human checkpoint
#  (sending things, deleting things, changing the world outside the project).
# ══════════════════════════════════════════════════════════════════════════

# Tools that always need a yes, no matter the arguments.
_ALWAYS_CONFIRM = {"shutdown_computer", "delete_file"}

# Shell/code that changes state (vs. read-only inspection like `git status`).
_MUTATING_CMD = re.compile(
    r"\b(git\s+(push|commit|reset|checkout|merge|rebase)|pip\s+(install|uninstall)|"
    r"npm\s+(install|uninstall|publish)|del|erase|rmdir|rd\b|move|ren\b|mklink|"
    r"reg\s+add|reg\s+delete|schtasks|net\s+user|taskkill|curl\s+.*(-x|--request)\s*post|"
    r"shutil\.rmtree|os\.remove|os\.rmdir|os\.unlink|\.unlink\(|send)\b",
    re.IGNORECASE,
)

# Browser tasks that publish, purchase or submit on the user's behalf.
_SENSITIVE_BROWSER = re.compile(
    r"\b(send|submit|purchase|buy|order|post|publish|reply|sign\s*up|register|"
    r"log\s*in|login|checkout|pay|transfer|delete|unsubscribe)\b",
    re.IGNORECASE,
)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _inside_project(path: str) -> bool:
    try:
        target = os.path.abspath(os.path.expanduser(path))
        return os.path.commonpath([target, _PROJECT_ROOT]) == _PROJECT_ROOT
    except Exception:
        return False


def needs_approval(tool_name: str, args: dict, entry: dict | None, config: dict) -> bool:
    """True when this call must wait for the user's explicit approval."""
    cfg = _cfg(config)
    if cfg.get("unrestricted") or cfg.get("approval_mode", "confirm") == "off":
        return False
    if tool_name in (cfg.get("never_confirm") or []):
        return False
    if tool_name in (cfg.get("always_confirm") or []):
        return True
    if entry and entry.get("approval") == "confirm":
        return True
    if tool_name in _ALWAYS_CONFIRM:
        return True

    args = args or {}
    if tool_name in ("run_terminal_command", "run_code"):
        cmd = str(args.get("command") or args.get("code") or "")
        return bool(_MUTATING_CMD.search(cmd))
    if tool_name in ("write_file", "edit_file"):
        path = str(args.get("path") or args.get("file_path") or "")
        return bool(path) and not _inside_project(path)
    if tool_name == "browser_task":
        return bool(_SENSITIVE_BROWSER.search(str(args.get("task") or "")))
    return False


def describe_action(tool_name: str, args: dict) -> str:
    """One human sentence for the approval card / spoken question."""
    args = args or {}
    if tool_name == "shutdown_computer":
        return f"shut down the computer in {args.get('delay_seconds', 30)}s"
    if tool_name == "delete_file":
        return f"delete the file {args.get('path') or args.get('file_path')}"
    if tool_name in ("write_file", "edit_file"):
        return f"modify {args.get('path') or args.get('file_path')} (outside the project)"
    if tool_name in ("run_terminal_command", "run_code"):
        cmd = str(args.get("command") or args.get("code") or "")[:80]
        return f"run the command: {cmd}"
    if tool_name == "browser_task":
        return f"do this in the browser: {str(args.get('task'))[:100]}"
    preview = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
    return f"run {tool_name}({preview[:80]})"
