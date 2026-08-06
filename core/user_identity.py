"""
Who the user is — read from memory/MEMORY.md and nowhere else.

The user's name used to be baked into the personality prompt, every tool
description and half the docstrings in core/. That made the assistant
un-shareable and meant the name lived in ~30 places at once. Now the code says
"the user" everywhere, and the actual name comes from a single file:

    memory/MEMORY.md      (preferred)
    MEMORY.md             (project root, fallback)

The file is plain markdown. The name is the first of these that matches:

    - Name: Jane Doe
    Name: Jane Doe
    # Freya Memory — Jane Doe

Nothing else in the codebase — not the session-extraction prompt, not the
Windows account folder, not the config — is allowed to be a source for it.
"""

import os
import re
import threading

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

MEMORY_MD_PATHS = (
    os.path.join(_ROOT, "memory", "MEMORY.md"),
    os.path.join(_ROOT, "MEMORY.md"),
)

_NAME_LINE = re.compile(r"^\s*[-*]?\s*name\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
_PREFERRED_LINE = re.compile(
    r"^\s*[-*]?\s*(?:preferred\s*name|nickname|goes\s*by|call\s*me)\s*[:=]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_NAME_HEADING = re.compile(r"^#\s*.*?[—–-]\s*(.+?)\s*$")

_lock = threading.Lock()
_cache: dict[str, object] = {"path": None, "mtime": None, "text": "", "name": ""}


def memory_md_path() -> str | None:
    """The MEMORY.md actually in use, or None if the user hasn't made one."""
    for path in MEMORY_MD_PATHS:
        if os.path.exists(path):
            return path
    return None


def _parse_name(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            m = _NAME_HEADING.match(stripped)
            if m and not m.group(1).startswith("["):
                heading_name = m.group(1).strip()
                if heading_name:
                    return heading_name
            continue
        m = _NAME_LINE.match(stripped)
        if m:
            name = m.group(1).strip()
            # Ignore the placeholder from MEMORY.example.md.
            if name and not name.startswith("["):
                return name
    return ""


def _load() -> tuple[str, str]:
    """(full markdown, name) — re-read only when the file changes on disk."""
    path = memory_md_path()
    with _lock:
        if path is None:
            _cache.update(path=None, mtime=None, text="", name="")
            return "", ""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if _cache["path"] == path and _cache["mtime"] == mtime:
            return str(_cache["text"]), str(_cache["name"])
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(f"  MEMORY.md could not be read ({e}); continuing without a user name.")
            text = ""
        _cache.update(path=path, mtime=mtime, text=text, name=_parse_name(text))
        return str(_cache["text"]), str(_cache["name"])


def get_user_name(default: str = "") -> str:
    """The user's name from MEMORY.md, or `default` if it isn't recorded there."""
    return _load()[1] or default


def get_preferred_name(default: str = "") -> str:
    """What to actually call the user out loud.

    A voice assistant saying "Ihan Hansaja" every time would be absurd, so this
    is the spoken form: an explicit `Preferred name:` / `Nickname:` / `Call me:`
    line in MEMORY.md if there is one, otherwise the first word of the name.
    """
    text, full = _load()
    for line in text.splitlines():
        m = _PREFERRED_LINE.match(line.strip())
        if m:
            preferred = m.group(1).strip()
            if preferred and not preferred.startswith("["):
                return preferred
    return (full.split()[0] if full else "") or default


def get_user_profile() -> str:
    """The whole MEMORY.md, to inject into the system prompt. '' if absent."""
    return _load()[0].strip()


def address_user() -> str:
    """How to refer to the user in generated text — their name, else 'the user'."""
    return get_user_name("the user")
