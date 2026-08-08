"""
User folder resolution — where "my desktop" actually is.

Freya kept failing to write to well-known locations because she had no way to
*know* them, so she guessed from conversation: the user goes by a first name, so
she'd try `C:\\Users\\<first name>\\Desktop`, Windows denied it (WinError 5), and
she'd silently fall back to the project folder. The safety sandbox was
never involved — the path simply didn't exist.

This module resolves the real locations through the Windows shell
(SHGetKnownFolderPath), which is authoritative and, unlike string-building from
%USERPROFILE%, follows OneDrive/enterprise folder redirection. Every file tool
routes its path argument through `resolve_user_path`, so all of these land in
the same real place:

    "desktop/notes.txt"                     "~/Desktop/notes.txt"
    "%USERPROFILE%/Desktop/notes.txt"       "C:/Users/Jane Doe/Desktop/notes.txt"
"""

import ctypes
import ctypes.wintypes
import os
import re

# Shell "known folder" GUIDs (shlobj.h). Resolved at runtime rather than
# assembled from the username, so redirected folders resolve correctly.
_KNOWN_FOLDERS = {
    "desktop":   "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures":  "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music":     "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos":    "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}

# Spoken/typed aliases people (and language models) actually use.
_ALIASES = {
    "desktop": "desktop", "my desktop": "desktop",
    "documents": "documents", "my documents": "documents", "docs": "documents",
    "downloads": "downloads", "download": "downloads", "my downloads": "downloads",
    "pictures": "pictures", "photos": "pictures", "images": "pictures",
    "music": "music", "videos": "videos", "movies": "videos",
    "home": "home", "user": "home", "userprofile": "home",
}

_cache: dict[str, str] = {}


def _known_folder(key: str) -> str | None:
    """Ask Windows where a known folder really is. None if unavailable."""
    guid = _KNOWN_FOLDERS.get(key)
    if not guid:
        return None
    if key in _cache:
        return _cache[key]
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.wintypes.DWORD),
                ("Data2", ctypes.wintypes.WORD),
                ("Data3", ctypes.wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        folder_id = GUID()
        if ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(folder_id)) != 0:
            return None
        out = ctypes.c_wchar_p()
        # 0 = no special flags, None = current user
        if ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(out)
        ) != 0:
            return None
        path = out.value
        ctypes.windll.ole32.CoTaskMemFree(out)
        if path:
            _cache[key] = path
            return path
    except Exception:
        pass
    return None


def _fallback(key: str) -> str:
    home = os.path.expanduser("~")
    return home if key == "home" else os.path.join(home, key.capitalize())


def user_folder(name: str) -> str:
    """Absolute path of a well-known folder ('desktop', 'downloads', 'home'…)."""
    key = _ALIASES.get(name.strip().lower(), name.strip().lower())
    if key == "home":
        return os.path.expanduser("~")
    return _known_folder(key) or _fallback(key)


def all_user_folders() -> dict[str, str]:
    folders = {"home": os.path.expanduser("~")}
    for key in _KNOWN_FOLDERS:
        folders[key] = user_folder(key)
    return folders


# Leading "desktop/..." or "desktop\..." (with no drive/root in front).
_LEADING_ALIAS = re.compile(r"^(?P<name>[A-Za-z ]+?)[\\/](?P<rest>.*)$")


def resolve_user_path(path: str) -> str:
    """Normalize any way a path might be expressed into a real absolute path.

    Handles `~`, environment variables (%USERPROFILE%, $HOME), and bare
    well-known folder names used as the first segment ("desktop/notes.txt").
    Anything already absolute is returned unchanged apart from normalization,
    so this never rewrites a path the caller was explicit about.
    """
    if not path:
        return path
    p = str(path).strip().strip('"').strip("'")

    p = os.path.expandvars(os.path.expanduser(p))

    # A bare alias on its own ("desktop") -> that folder.
    if p.lower() in _ALIASES:
        return user_folder(p)

    # Alias as the first segment ("desktop/notes.txt"), only when the path
    # isn't already rooted — an absolute path is taken at its word.
    if not os.path.isabs(p) and not re.match(r"^[A-Za-z]:", p):
        m = _LEADING_ALIAS.match(p)
        if m and m.group("name").strip().lower() in _ALIASES:
            return os.path.normpath(os.path.join(user_folder(m.group("name")), m.group("rest")))

    return os.path.normpath(os.path.abspath(p))
