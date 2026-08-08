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
from core.user_paths import resolve_user_path

# Patterns that are never allowed in a shell command, regardless of config.
#
# Two families here. The originals are blunt data-destroyers. The additions are
# the quieter ones that matter more in practice: a command that leaves the disk
# intact but the machine unbootable, unrecoverable, or defenceless. Deleting
# shadow copies is the one that turns an ordinary mistake into an unrecoverable
# one, since it removes the restore points you would fix it from.
_HARD_BLOCK = [
    # Data destruction
    "rm -rf", "rm -fr", ":(){", "mkfs", "format ", "del /f", "del /q",
    "rmdir /s", "format c:", "diskpart", "> /dev/sda", "dd if=", "shutdown -r",
    # Boot / partition
    "bcdedit", "bootrec", "bcdboot", "fdisk", "gpt /clear", "clean all",
    # Recovery removal — this is what makes a mistake permanent
    "vssadmin delete", "wbadmin delete", "wmic shadowcopy delete",
    "delete shadows", "cipher /w", "sdelete",
    # Security posture
    "set-mppreference -disablerealtimemonitoring", "disablerealtimemonitoring",
    "netsh advfirewall set allprofiles state off", "sc delete windefend",
    "takeown /f c:\\windows", "icacls c:\\windows",
    # System integrity / registry hives
    "reg delete hklm", "reg delete hkey_local_machine", "reg unload",
    "sfc /scannow /offbootdir", "dism /online /cleanup-image /restorehealth /source:none",
]

# ══════════════════════════════════════════════════════════════════════════
#  PROTECTED ZONES
#
#  The allow-list (`allowed_roots`) answers "where may Freya work". It does not
#  answer "where must she never break things" — and with the roots set to whole
#  drives, as they are here, it answers nothing at all: C:\ includes C:\Windows.
#
#  So classification runs first, and it is a deny-list, deliberately:
#
#    SYSTEM     Windows, Program Files, boot, drivers. Read freely — she should
#               be able to look at a config or a log. Never write, never delete.
#               Not overridable by `unrestricted`; it takes an explicit
#               `safety.protect_system: false` to lift, because "let her off the
#               leash" should not silently mean "let her delete System32".
#
#    PROTECTED  Source repositories and Freya's own state. She is a coding
#               assistant, so editing files here is her job and stays allowed.
#               What is blocked is the class of operation that loses work rather
#               than changes it: deleting or moving a repo, or touching .git
#               internals, where a single bad call costs history you cannot
#               retype.
# ══════════════════════════════════════════════════════════════════════════

def _system_roots() -> list[str]:
    """Windows' own territory, resolved from the environment rather than
    hardcoded to C: — Windows is not always on C:, and a machine that installs
    it elsewhere would otherwise be completely unprotected."""
    roots = []
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
                "ProgramData", "SystemDrive"):
        value = os.environ.get(var)
        if not value:
            continue
        if var == "SystemDrive":
            # Not the whole drive — just the boot furniture sitting at its root.
            for leaf in ("$Recycle.Bin", "System Volume Information", "Recovery",
                         "Boot", "EFI", "PerfLogs", "bootmgr", "pagefile.sys",
                         "hiberfil.sys", "swapfile.sys"):
                roots.append(os.path.join(value + os.sep, leaf))
            continue
        roots.append(value)
    if not roots:  # non-Windows or a stripped environment
        roots = ["C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)"]
    return [os.path.normcase(os.path.abspath(r)) for r in roots]


_SYSTEM_ROOTS = _system_roots()

# Directory names that mark a folder as the root of somebody's work.
_PROJECT_MARKERS = (".git", ".hg", ".svn")

# Freya's own state. Losing this is losing her memory, and she is perfectly
# capable of being talked into "clean up that database file for me".
_OWN_STATE = ("memory", "config")

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def zone_of(path: str, config: dict | None = None) -> str:
    """Classify a path: 'system', 'protected', or 'user'."""
    try:
        target = os.path.normcase(resolve_user_path(path))
    except Exception:
        return "user"

    cfg = _cfg(config or {})

    if cfg.get("protect_system", True):
        roots = _SYSTEM_ROOTS + [os.path.normcase(os.path.abspath(os.path.expanduser(r)))
                                 for r in (cfg.get("protected_system_roots") or [])]
        for root in roots:
            if target == root or target.startswith(root + os.sep):
                return "system"

    if cfg.get("protect_projects", True):
        # Freya's own memory and config.
        for leaf in _OWN_STATE:
            own = os.path.normcase(os.path.join(_PROJECT_ROOT, leaf))
            if target == own or target.startswith(own + os.sep):
                return "protected"
        # Anything inside a version-control directory, and any repo root itself.
        parts = target.split(os.sep)
        if any(p in _PROJECT_MARKERS for p in parts):
            return "protected"
        if _is_repo_root(target):
            return "protected"

    return "user"


def _is_repo_root(target: str) -> bool:
    """Is this path itself a repository root (i.e. does it contain .git)?

    Only the root is protected, not everything under it — editing a source file
    must stay ordinary work. It is deleting or moving the repo that is not.
    """
    try:
        if not os.path.isdir(target):
            return False
        return any(os.path.exists(os.path.join(target, m)) for m in _PROJECT_MARKERS)
    except Exception:
        return False


# Operations that destroy or relocate rather than edit.
# `undo_organize` is deliberately absent: putting things back must always work,
# even if the folder has since been classified as protected.
_DESTRUCTIVE_TOOLS = {
    "delete_file", "delete_item", "move_item", "unzip_archive", "organize_folder",
}


def check_zone(tool_name: str, path: str, config: dict) -> tuple[bool, str]:
    """Zone rules for one path argument of one tool."""
    zone = zone_of(path, config)

    if zone == "system":
        return False, (
            f"'{path}' is part of Windows itself, so I won't write to it or delete it — "
            "that's how a PC gets broken. I can read from there if you need to see "
            "something. If you genuinely need this changed, do it yourself with an admin "
            "prompt, or turn off safety.protect_system in my config."
        )

    if zone == "protected" and tool_name in _DESTRUCTIVE_TOOLS:
        return False, (
            f"'{path}' is a project or my own memory, so I won't delete or move it — "
            "you'd lose work or history that can't be retyped. I can still edit files "
            "inside it, or copy it somewhere safe first if you want a backup."
        )

    return True, ""


_safety_cache: tuple[float, dict] | None = None


def _live_safety() -> dict | None:
    """Read the `safety` block straight from disk, cached on file mtime.

    A live voice session snapshots the config once at start (`run_freya`), so
    changing access control from the dashboard used to have no effect until the
    session was restarted — you'd flip "unrestricted" on, watch nothing change,
    and reasonably conclude the setting was broken. Re-reading here makes
    access-control edits apply to the very next tool call.
    """
    global _safety_cache
    path = os.path.join(os.path.dirname(__file__), "..", "config", "freya_config.json")
    try:
        mtime = os.path.getmtime(path)
        if _safety_cache and _safety_cache[0] == mtime:
            return _safety_cache[1]
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f).get("safety", {}) or {}
        _safety_cache = (mtime, data)
        return data
    except Exception:
        return None  # fall back to the caller's snapshot


def _cfg(config: dict) -> dict:
    live = _live_safety()
    if live is not None:
        return live
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
    in natural title case ("Jane Doe") rather than however the actual
    Windows account folder happens to be cased ("JANE DOE") — a naive
    case-sensitive compare here would then hard-block access to a folder
    (like the user's own Desktop) that Windows would happily write to and
    that may even be explicitly listed in safety.allowed_roots.
    """
    try:
        target = os.path.normcase(resolve_user_path(path))
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
    """Main entry point used by the registry for tools flagged dangerous.

    Order matters. The protected-zone checks run FIRST and are not waived by
    `unrestricted`, because that flag means "I trust her with my files", not
    "I accept an unbootable machine". Everything after it is the older
    allow-list behaviour, unchanged.
    """
    cfg = _cfg(config)
    unrestricted = bool(cfg.get("unrestricted"))

    # ── Always-on protection ──────────────────────────────────────────────
    cmd = args.get("command") or args.get("code") or ""
    if cmd:
        ok, msg = check_command(str(cmd))
        if not ok:
            return ok, msg
        ok, msg = check_command_targets(str(cmd), config)
        if not ok:
            return ok, msg

    for arg_name in _PATH_ARGS.get(tool_name, ()):
        # Skip arguments the tool only reads from. Copying a file OUT of
        # System32 or zipping a system folder for inspection harms nothing —
        # it's writing to or deleting from those places that does. Blocking
        # reads would just make her unable to look at a driver config.
        if arg_name in _READ_ONLY_ARGS.get(tool_name, ()):
            continue
        path = args.get(arg_name) or ""
        if path:
            ok, msg = check_zone(tool_name, str(path), config)
            if not ok:
                return ok, msg

    if unrestricted:
        return True, ""  # user opted out of the allow-list, but not of the above

    # ── Allow-list ────────────────────────────────────────────────────────
    # File-touching tools must stay inside allowed roots. Each entry names the
    # argument(s) that carry a path — file_manager tools use source/destination
    # rather than `path`, and BOTH ends of a copy/move must be checked (a move
    # out of an allowed root is just as much an escape as a move into one).
    for arg_name in _PATH_ARGS.get(tool_name, ()):
        path = args.get(arg_name) or ""
        if path and not path_is_allowed(str(path), config):
            return False, (
                f"For safety I can only touch files inside your home folder or the Freya "
                f"project. '{path}' is outside that. Add it to safety.allowed_roots to permit it."
            )

    return True, ""


# A shell command that names a protected location AND does something
# destructive to it. Pattern-matching a command line is weaker than checking a
# resolved path, so this is a backstop for the obvious cases — `del C:\Windows\...`
# should not succeed just because it arrived as a string instead of a path arg.
_DESTRUCTIVE_VERB = re.compile(
    r"\b(del|erase|rd|rmdir|move|ren|rename|takeown|icacls|attrib|copy|xcopy|robocopy|"
    r"remove-item|move-item|rename-item|set-content|out-file|new-item)\b",
    re.IGNORECASE,
)

# Windows paths inside a command string, quoted or bare.
_PATH_IN_CMD = re.compile(r'"([A-Za-z]:\\[^"]+)"|([A-Za-z]:\\[^\s;|&"]+)')


def check_command_targets(command: str, config: dict) -> tuple[bool, str]:
    """Block a shell command that would destroy something in a protected zone."""
    if not _DESTRUCTIVE_VERB.search(command):
        return True, ""
    for match in _PATH_IN_CMD.finditer(command):
        path = match.group(1) or match.group(2)
        if not path:
            continue
        if zone_of(path, config) == "system":
            return False, (
                f"That command would modify '{path}', which is part of Windows itself. "
                "I won't run it — a bad path there can stop the machine booting."
            )
    return True, ""


# Arguments a tool only READS from. These are exempt from the zone rules but
# still subject to the allow-list. Note `move_item.source` is deliberately NOT
# here: a move deletes the original.
_READ_ONLY_ARGS: dict[str, tuple[str, ...]] = {
    "copy_item": ("source",),
    "zip_item": ("source",),
    "unzip_archive": ("path",),
}

# Which argument(s) each dangerous file tool puts its path in.
_PATH_ARGS: dict[str, tuple[str, ...]] = {
    "write_file": ("path", "file_path"),
    "edit_file": ("path", "file_path"),
    "delete_file": ("path", "file_path"),
    "create_tool": ("path", "file_path"),
    # core/file_manager.py
    "copy_item": ("source", "destination"),
    "move_item": ("source", "destination"),
    "delete_item": ("path",),
    "create_folder": ("path",),
    "zip_item": ("source", "destination"),
    "unzip_archive": ("path", "destination"),
    # core/organizer.py
    "organize_folder": ("folder",),
    "undo_organize": ("folder",),
}


# ══════════════════════════════════════════════════════════════════════════
#  Approval rules — which actions must pause for the user's explicit yes.
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
        target = resolve_user_path(path)
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
