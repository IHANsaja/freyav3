"""
File manager — real Windows file operations beyond read/write/list.

core/system_tools.py already covers the basics (read_file, write_file, list_dir,
search_files). This suite adds the operations you'd actually use a file explorer
for: copying, moving/renaming, deleting to the Recycle Bin, creating folders,
inspecting metadata, opening files in their default app, revealing them in
Explorer, zipping/unzipping, and answering "where did my disk space go".

Design notes
------------
• Deletes go to the **Recycle Bin** (via send2trash) rather than being permanent,
  so a misheard voice command is always recoverable. `permanent=true` opts out.
• Everything that creates, moves or destroys data is `dangerous=True`, so it
  passes through core/safety.py's allowed-roots gate first (see safety.py's
  _PATH_ARG_TOOLS list, which names the argument each tool puts its path in).
• Sizes are returned human-readable ("1.4 GB") because a voice model reads these
  aloud — raw byte counts are useless spoken.
• Third-party imports are local + guarded so a missing optional package disables
  only that one tool rather than breaking the skill.
"""

import os
import shutil
import subprocess
import time
import zipfile

from core.registry import tool, OBJ, P, STR, BOOL, INT
from core.user_paths import resolve_user_path

MAX_LIST = 40  # entries returned to a voice model before truncating


def _x(path: str) -> str:
    return resolve_user_path(path or "")


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _when(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _dest_for(src: str, dst: str) -> str:
    """If dst is an existing directory, keep src's basename inside it."""
    return os.path.join(dst, os.path.basename(src)) if os.path.isdir(dst) else dst


# ══════════════════════════════════════════════
#  COPY / MOVE / RENAME
# ══════════════════════════════════════════════
@tool(
    "copy_item",
    "Copy a file or an entire folder to another location. Works for both — folders are "
    "copied recursively with everything inside them.",
    OBJ({"source": P(STR, "Path of the file or folder to copy"),
         "destination": P(STR, "Destination path, or an existing folder to copy into"),
         "overwrite": P(BOOL, "Replace the destination if it already exists (default false)")},
        ["source", "destination"]),
    dangerous=True,
)
def copy_item(args, ctx) -> str:
    src, dst = _x(args.get("source", "")), _x(args.get("destination", ""))
    if not os.path.exists(src):
        return f"There's nothing at {src}."
    dst = _dest_for(src, dst)
    if os.path.exists(dst) and not args.get("overwrite"):
        return f"{dst} already exists. Say overwrite if you want me to replace it."
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            return f"Copied the folder {os.path.basename(src)} to {dst}."
        shutil.copy2(src, dst)
        return f"Copied {os.path.basename(src)} to {dst}."
    except Exception as e:
        return f"Couldn't copy that: {e}"


@tool(
    "move_item",
    "Move or rename a file or folder. Renaming is just moving it to a new name in the same "
    "folder — use this for both.",
    OBJ({"source": P(STR, "Path of the file or folder to move"),
         "destination": P(STR, "New full path, or an existing folder to move it into"),
         "overwrite": P(BOOL, "Replace the destination if it already exists (default false)")},
        ["source", "destination"]),
    dangerous=True,
)
def move_item(args, ctx) -> str:
    src, dst = _x(args.get("source", "")), _x(args.get("destination", ""))
    if not os.path.exists(src):
        return f"There's nothing at {src}."
    dst = _dest_for(src, dst)
    if os.path.exists(dst):
        if not args.get("overwrite"):
            return f"{dst} already exists. Say overwrite if you want me to replace it."
        try:
            shutil.rmtree(dst) if os.path.isdir(dst) else os.remove(dst)
        except Exception as e:
            return f"Couldn't clear the destination: {e}"
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.move(src, dst)
        same_parent = os.path.dirname(src) == os.path.dirname(dst)
        verb = "Renamed" if same_parent else "Moved"
        return f"{verb} {os.path.basename(src)} to {os.path.basename(dst)}."
    except Exception as e:
        return f"Couldn't move that: {e}"


# ══════════════════════════════════════════════
#  DELETE / CREATE
# ══════════════════════════════════════════════
@tool(
    "delete_item",
    "Delete a file or folder. By default it goes to the Windows Recycle Bin so it can be "
    "restored; only set permanent when the user explicitly asks for it to be gone for good.",
    OBJ({"path": P(STR, "Path of the file or folder to delete"),
         "permanent": P(BOOL, "Bypass the Recycle Bin and erase it irreversibly (default false)")},
        ["path"]),
    dangerous=True,
    approval="confirm",
)
def delete_item(args, ctx) -> str:
    path = _x(args.get("path", ""))
    if not os.path.exists(path):
        return f"There's nothing at {path}."
    kind = "folder" if os.path.isdir(path) else "file"
    name = os.path.basename(path)
    if not args.get("permanent"):
        try:
            from send2trash import send2trash
            send2trash(path)
            return f"Sent the {kind} {name} to the Recycle Bin — say the word if you want it back."
        except ImportError:
            return ("I can't reach the Recycle Bin (the send2trash package isn't installed). "
                    "Run 'pip install send2trash', or ask me again with permanent delete.")
        except Exception as e:
            return f"Couldn't recycle that: {e}"
    try:
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        return f"Permanently deleted the {kind} {name}."
    except Exception as e:
        return f"Couldn't delete that: {e}"


@tool(
    "create_folder",
    "Create a new folder (including any missing parent folders).",
    OBJ({"path": P(STR, "Full path of the folder to create")}, ["path"]),
    dangerous=True,
)
def create_folder(args, ctx) -> str:
    path = _x(args.get("path", ""))
    if os.path.isdir(path):
        return f"{path} already exists."
    try:
        os.makedirs(path, exist_ok=True)
        return f"Created the folder {path}."
    except Exception as e:
        return f"Couldn't create that folder: {e}"


# ══════════════════════════════════════════════
#  INSPECT
# ══════════════════════════════════════════════
@tool(
    "get_user_folders",
    "Look up the REAL paths of the user's standard folders (desktop, documents, downloads, "
    "pictures, music, videos, home). Use this whenever he refers to one by name and you "
    "need a concrete path — never guess his username or build the path yourself, because "
    "the account folder is often not what you'd expect from his first name.",
    OBJ(),
)
def get_user_folders(args, ctx) -> str:
    from core.user_paths import all_user_folders
    folders = all_user_folders()
    return "the user's folders: " + "; ".join(f"{k} = {v}" for k, v in folders.items())


@tool(
    "file_info",
    "Get details about a file or folder: size, when it was created and last modified, and "
    "for folders how many items it holds.",
    OBJ({"path": P(STR, "Path to inspect")}, ["path"]),
)
def file_info(args, ctx) -> str:
    path = _x(args.get("path", ""))
    if not os.path.exists(path):
        return f"There's nothing at {path}."
    try:
        st = os.stat(path)
        name = os.path.basename(path) or path
        if os.path.isdir(path):
            try:
                entries = os.listdir(path)
                files = sum(1 for e in entries if os.path.isfile(os.path.join(path, e)))
                folders = len(entries) - files
                counts = f"{files} file(s) and {folders} folder(s) directly inside"
            except OSError:
                counts = "contents unreadable"
            return (f"{name} is a folder holding {counts}, totalling {_human(_dir_size(path))}. "
                    f"Last modified {_when(st.st_mtime)}.")
        return (f"{name} is a {_human(st.st_size)} file, created {_when(st.st_ctime)}, "
                f"last modified {_when(st.st_mtime)}.")
    except Exception as e:
        return f"Couldn't read that: {e}"


@tool(
    "disk_usage",
    "Report free and used space on a drive.",
    OBJ({"drive": P(STR, "Drive or path to check, e.g. C: (defaults to C:)")}),
)
def disk_usage(args, ctx) -> str:
    target = _x(args.get("drive") or "C:\\")
    try:
        total, used, free = shutil.disk_usage(target)
        pct = used / total * 100 if total else 0
        return (f"{target} has {_human(free)} free of {_human(total)} — "
                f"that's {pct:.0f} percent used.")
    except Exception as e:
        return f"Couldn't check disk space: {e}"


@tool(
    "find_files_by",
    "Find files in a folder ranked by size or how recently they changed — use this for "
    "'what's taking up space', 'what did I work on recently', 'biggest files in Downloads'.",
    OBJ({"directory": P(STR, "Folder to search (searches subfolders too)"),
         "sort_by": P(STR, "Either 'largest' or 'recent'", enum=["largest", "recent"]),
         "limit": P(INT, "How many to return (default 10, max 40)")},
        ["directory", "sort_by"]),
)
def find_files_by(args, ctx) -> str:
    directory = _x(args.get("directory", "~"))
    if not os.path.isdir(directory):
        return f"{directory} isn't a folder I can open."
    mode = (args.get("sort_by") or "largest").lower()
    limit = max(1, min(int(args.get("limit") or 10), MAX_LIST))
    found = []
    for root, dirs, files in os.walk(directory, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
                found.append((fp, st.st_size, st.st_mtime))
            except OSError:
                pass
        if len(found) > 20_000:  # keep a runaway walk from hanging the voice loop
            break
    if not found:
        return f"I didn't find any files under {directory}."
    idx = 1 if mode == "largest" else 2
    found.sort(key=lambda t: t[idx], reverse=True)
    label = "largest" if mode == "largest" else "most recently changed"
    lines = [f"{os.path.basename(p)} ({_human(s)}, {_when(m)})" for p, s, m in found[:limit]]
    return f"The {limit} {label} files under {directory}: " + "; ".join(lines)


# ══════════════════════════════════════════════
#  SHELL INTEGRATION
# ══════════════════════════════════════════════
@tool(
    "open_path",
    "Open a file or folder in whatever Windows app handles it — a document in Word, a photo "
    "in the viewer, a folder in Explorer.",
    OBJ({"path": P(STR, "Path of the file or folder to open")}, ["path"]),
)
def open_path(args, ctx) -> str:
    path = _x(args.get("path", ""))
    if not os.path.exists(path):
        return f"There's nothing at {path}."
    try:
        os.startfile(path)  # noqa: S606 — Windows shell "open" verb
        return f"Opened {os.path.basename(path) or path}."
    except AttributeError:
        return "Opening files this way only works on Windows."
    except Exception as e:
        return f"Couldn't open that: {e}"


@tool(
    "reveal_in_explorer",
    "Open File Explorer with a specific file highlighted, so the user can see where it lives.",
    OBJ({"path": P(STR, "Path of the file to reveal")}, ["path"]),
)
def reveal_in_explorer(args, ctx) -> str:
    path = _x(args.get("path", ""))
    if not os.path.exists(path):
        return f"There's nothing at {path}."
    try:
        subprocess.Popen(["explorer", "/select,", path])
        return f"There it is — I've highlighted {os.path.basename(path)} in Explorer."
    except Exception as e:
        return f"Couldn't open Explorer: {e}"


# ══════════════════════════════════════════════
#  ARCHIVES
# ══════════════════════════════════════════════
@tool(
    "zip_item",
    "Compress a file or folder into a .zip archive.",
    OBJ({"source": P(STR, "File or folder to compress"),
         "destination": P(STR, "Path for the .zip file (defaults to alongside the source)")},
        ["source"]),
    dangerous=True,
)
def zip_item(args, ctx) -> str:
    src = _x(args.get("source", ""))
    if not os.path.exists(src):
        return f"There's nothing at {src}."
    dst = _x(args.get("destination")) if args.get("destination") else src.rstrip("\\/") + ".zip"
    if not dst.lower().endswith(".zip"):
        dst += ".zip"
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isfile(src):
                z.write(src, os.path.basename(src))
            else:
                base = os.path.dirname(src.rstrip("\\/"))
                for root, _dirs, files in os.walk(src):
                    for f in files:
                        fp = os.path.join(root, f)
                        z.write(fp, os.path.relpath(fp, base))
        return f"Zipped it up — {os.path.basename(dst)} is {_human(os.path.getsize(dst))}."
    except Exception as e:
        return f"Couldn't create that archive: {e}"


@tool(
    "unzip_archive",
    "Extract a .zip archive into a folder.",
    OBJ({"path": P(STR, "The .zip file to extract"),
         "destination": P(STR, "Folder to extract into (defaults to a folder beside the zip)")},
        ["path"]),
    dangerous=True,
)
def unzip_archive(args, ctx) -> str:
    path = _x(args.get("path", ""))
    if not os.path.isfile(path):
        return f"There's no archive at {path}."
    dst = _x(args.get("destination")) if args.get("destination") else os.path.splitext(path)[0]
    try:
        with zipfile.ZipFile(path) as z:
            # Guard against zip-slip: entries that escape the destination folder.
            for member in z.namelist():
                target = os.path.abspath(os.path.join(dst, member))
                if os.path.commonpath([target, os.path.abspath(dst)]) != os.path.abspath(dst):
                    return f"That archive contains an unsafe path ({member}); I won't extract it."
            z.extractall(dst)
            count = len(z.namelist())
        return f"Extracted {count} item(s) into {dst}."
    except zipfile.BadZipFile:
        return "That doesn't look like a valid zip archive."
    except Exception as e:
        return f"Couldn't extract that: {e}"
