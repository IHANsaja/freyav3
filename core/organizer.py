"""
Tidy Up — turn a cluttered folder into a sorted one in a single call.

Freya could already do this the long way: `list_dir`, then `create_folder`, then
one `move_item` per file. On a real desktop that's forty-plus round trips through
a live voice model, each one a chance to mis-hear a filename, drift, or stall
half-way — leaving the desktop *worse* than it started, with no way back. So the
categorisation lives here in Python and the model makes exactly one call.

Design notes
------------
• **Undo is the safety net.** These tools run without an approval prompt, so
  every run writes a manifest of exactly what moved where (memory/organize_undo.json)
  and `undo_organize` puts it all back. Nothing is ever deleted or overwritten —
  a name collision gets " (2)" appended.
• **Shortcuts stay put.** Filing a .lnk into Documents/ defeats the entire point
  of having it on the desktop. Same for anything hidden or system-flagged.
• **Repos and system folders are skipped mid-scan**, not just at the top level:
  a git checkout sitting on the desktop is somebody's work, and moving it breaks
  every path that points at it. `core/safety.py` guards the folder argument;
  this guards each thing *inside* it.
• **`min_group` (default 2)** stops the silly outcome where one stray .zip earns
  a whole Archives/ folder. Singletons are left where they are.
• Re-running is a no-op: bucket folders are recognised and skipped, so "tidy my
  desktop" twice in a row doesn't nest Images/ inside Images/.
"""

import json
import os
import shutil
import time

from core.registry import tool, OBJ, P, STR, BOOL, INT
from core.safety import zone_of
from core.user_paths import resolve_user_path

_MANIFEST = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "memory", "organize_undo.json")
)

DEFAULT_MIN_GROUP = 2
MAX_PREVIEW = 8  # filenames listed back in a dry run before summarising

# Extension -> bucket. Deliberately a flat, boring lookup: the whole value of
# this tool over asking the model to sort things is that the answer is the same
# every time.
BUCKETS: dict[str, tuple[str, ...]] = {
    "Images":     ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "heic", "tiff", "ico"),
    "Documents":  ("pdf", "doc", "docx", "txt", "md", "rtf", "odt", "ppt", "pptx",
                   "xls", "xlsx", "csv", "epub"),
    "Videos":     ("mp4", "mkv", "mov", "avi", "webm", "wmv", "flv"),
    "Music":      ("mp3", "wav", "flac", "m4a", "aac", "ogg"),
    "Installers": ("exe", "msi", "msix", "appx"),
    "Archives":   ("zip", "rar", "7z", "tar", "gz", "iso"),
    "Code":       ("py", "js", "ts", "tsx", "html", "css", "json", "ps1", "bat", "sh",
                   "java", "c", "cpp", "cs", "go", "rs", "sql", "ipynb"),
}
OTHER = "Other"

_EXT_TO_BUCKET = {ext: name for name, exts in BUCKETS.items() for ext in exts}
_BUCKET_NAMES = set(BUCKETS) | {OTHER}

# How each bucket is spoken. Every return value here is read aloud, so a folder
# name that works on disk ("Music", "Code") needs a noun that works in a
# sentence — "8 music" is not something a person says.
_LABELS = {
    "Images":     ("image", "images"),
    "Documents":  ("document", "documents"),
    "Videos":     ("video", "videos"),
    "Music":      ("music file", "music files"),
    "Installers": ("installer", "installers"),
    "Archives":   ("archive", "archives"),
    "Code":       ("code file", "code files"),
    OTHER:        ("odd file", "odd files"),
}

# Shortcuts are the reason a desktop exists. Never file them away.
_NEVER_MOVE_EXT = (".lnk", ".url")
_NEVER_MOVE_NAME = {"desktop.ini", "thumbs.db"}


def _x(path: str) -> str:
    return resolve_user_path(path or "")


def _is_hidden(path: str, name: str) -> bool:
    """Dotfile, or carrying the Windows hidden/system attribute."""
    if name.startswith("."):
        return True
    try:
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        return bool(attrs & 0x2 or attrs & 0x4)  # HIDDEN | SYSTEM
    except Exception:
        return False


def _bucket_for(name: str) -> str:
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    return _EXT_TO_BUCKET.get(ext, OTHER)


def _unique(dest: str) -> str:
    """A free path near `dest`. We never overwrite — this is a tidy-up, not a merge."""
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(dest)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


# ══════════════════════════════════════════════
#  MANIFEST
# ══════════════════════════════════════════════
def _load_manifest() -> dict:
    try:
        with open(_MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_manifest(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_MANIFEST), exist_ok=True)
        with open(_MANIFEST, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # a failed manifest must not fail the tidy-up itself


# ══════════════════════════════════════════════
#  PLANNING
# ══════════════════════════════════════════════
def _build_plan(folder: str, include_folders: bool, min_group: int, config: dict):
    """Returns (groups, skipped) where groups is {bucket: [abs paths]}."""
    groups: dict[str, list[str]] = {}
    skipped = {"shortcuts": 0, "folders": 0, "protected": 0, "hidden": 0}

    with os.scandir(folder) as it:
        for entry in it:
            name = entry.name
            path = entry.path

            if name.lower() in _NEVER_MOVE_NAME:
                continue
            if name.lower().endswith(_NEVER_MOVE_EXT):
                skipped["shortcuts"] += 1
                continue
            if _is_hidden(path, name):
                skipped["hidden"] += 1
                continue

            if entry.is_dir():
                if name in _BUCKET_NAMES:
                    continue  # our own bucket from a previous run — idempotent
                if not include_folders:
                    skipped["folders"] += 1
                    continue

            # A repo, or Windows' own territory, sitting inside the folder.
            if zone_of(path, config) in ("protected", "system"):
                skipped["protected"] += 1
                continue

            groups.setdefault(_bucket_for(name) if entry.is_file() else OTHER, []).append(path)

    # Singletons stay where they are — one stray file doesn't earn a folder.
    small = {b: len(p) for b, p in groups.items() if len(p) < min_group}
    for bucket in small:
        del groups[bucket]
    skipped["singletons"] = sum(small.values())
    return groups, skipped


def _n(count: int, singular: str, plural: str = "") -> str:
    """"1 shortcut" / "3 shortcuts". Never "1 item(s)" — this gets spoken."""
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _spoken(counts: dict[str, int]) -> str:
    """"11 images, 6 documents and 2 archives" — read aloud, not printed."""
    parts = [_n(n, *_LABELS.get(b, (b.lower(), b.lower())))
             for b, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "organize_folder",
    "Tidy up a cluttered folder by sorting its files into subfolders by type — Images, "
    "Documents, Videos, Music, Installers, Archives, Code, Other. Use this for 'organise my "
    "desktop', 'clean up my downloads', 'my desktop is a mess', 'sort out this folder'. "
    "Desktop shortcuts, hidden files and code projects are left exactly where they are, and "
    "the whole thing is reversible with undo_organize.",
    OBJ({"folder": P(STR, "Folder to tidy — defaults to his desktop. 'downloads', 'desktop', "
                         "or a full path"),
         "dry_run": P(BOOL, "Work out the plan and describe it without moving anything "
                            "(default false — normally just do it)"),
         "include_folders": P(BOOL, "Also file away subfolders, not just loose files "
                                    "(default false)"),
         "min_group": P(INT, "Don't create a category folder for fewer than this many items "
                             "(default 2)")}),
    dangerous=True,
)
def organize_folder(args, ctx) -> str:
    folder = _x(args.get("folder") or "desktop")
    if not os.path.isdir(folder):
        return f"There's no folder at {folder}."

    dry_run = bool(args.get("dry_run"))
    include_folders = bool(args.get("include_folders"))
    try:
        min_group = max(1, int(args.get("min_group") or DEFAULT_MIN_GROUP))
    except (TypeError, ValueError):
        min_group = DEFAULT_MIN_GROUP

    config = getattr(ctx, "config", None) or {}
    try:
        groups, skipped = _build_plan(folder, include_folders, min_group, config)
    except Exception as e:
        return f"Couldn't read that folder: {e}"

    where = "his desktop" if os.path.basename(folder).lower() == "desktop" else folder
    if not groups:
        left = skipped.get("singletons", 0)
        tail = (f" There's {_n(left, 'odd file')} loose, but not enough of any one kind "
                "to be worth its own folder.") if left else ""
        return f"Nothing to tidy in {where} — it's already sorted.{tail}"

    counts = {b: len(p) for b, p in groups.items()}
    total = sum(counts.values())

    if dry_run:
        sample = []
        for bucket, paths in sorted(groups.items()):
            names = [os.path.basename(p) for p in paths[:MAX_PREVIEW]]
            more = f" +{len(paths) - len(names)} more" if len(paths) > len(names) else ""
            sample.append(f"{bucket}: {', '.join(names)}{more}")
        return (f"Here's what I'd do to {where} — move {total} items into "
                f"{_spoken(counts)}.\n" + "\n".join(sample) +
                "\nNothing has moved yet. Say go ahead and I'll do it.")

    moves: list[list[str]] = []
    created: list[str] = []
    failed = 0
    for bucket, paths in groups.items():
        target = os.path.join(folder, bucket)
        if not os.path.isdir(target):
            try:
                os.makedirs(target, exist_ok=True)
                created.append(target)
            except Exception:
                failed += len(paths)
                continue
        for src in paths:
            dst = _unique(os.path.join(target, os.path.basename(src)))
            try:
                shutil.move(src, dst)
                moves.append([src, dst])
            except Exception:
                failed += 1

    manifest = _load_manifest()
    manifest[os.path.normcase(folder)] = {
        "when": time.time(), "moves": moves, "created": created,
    }
    _save_manifest(manifest)

    moved_counts: dict[str, int] = {}
    for _src, dst in moves:
        moved_counts[os.path.basename(os.path.dirname(dst))] = \
            moved_counts.get(os.path.basename(os.path.dirname(dst)), 0) + 1

    msg = f"Tidied {_n(len(moves), 'thing')} off {where} — {_spoken(moved_counts)}."
    if skipped["shortcuts"]:
        was = "is" if skipped["shortcuts"] == 1 else "are"
        msg += f" Your {_n(skipped['shortcuts'], 'shortcut')} {was} untouched."
    if skipped["protected"]:
        msg += f" I left {_n(skipped['protected'], 'project folder')} alone."
    if skipped.get("singletons"):
        msg += f" {_n(skipped['singletons'], 'one-off file')} stayed put."
    if failed:
        msg += f" {_n(failed, 'item')} wouldn't move — probably open in something."
    return msg + " Say undo if you don't like it."


@tool(
    "undo_organize",
    "Undo the last organize_folder run — put every file back exactly where it was and remove "
    "the category folders. Use when he says 'undo that', 'put it back', 'I don't like it'.",
    OBJ({"folder": P(STR, "The folder that was tidied — defaults to his desktop")}),
    dangerous=True,
)
def undo_organize(args, ctx) -> str:
    folder = _x(args.get("folder") or "desktop")
    manifest = _load_manifest()
    entry = manifest.get(os.path.normcase(folder))
    if not entry:
        return f"I don't have a record of tidying {folder}, so there's nothing to undo."

    restored = 0
    missing = 0
    for src, dst in reversed(entry.get("moves") or []):
        if not os.path.exists(dst):
            missing += 1
            continue
        try:
            os.makedirs(os.path.dirname(src) or ".", exist_ok=True)
            shutil.move(dst, _unique(src))
            restored += 1
        except Exception:
            missing += 1

    for target in entry.get("created") or []:
        try:
            if os.path.isdir(target) and not os.listdir(target):
                os.rmdir(target)
        except Exception:
            pass

    manifest.pop(os.path.normcase(folder), None)
    _save_manifest(manifest)

    where = "your desktop" if os.path.basename(folder).lower() == "desktop" else folder
    was = "it was" if restored == 1 else "they were"
    msg = f"Put {_n(restored, 'item')} back on {where} the way {was}."
    if missing:
        had = "that one" if missing == 1 else "those"
        msg += (f" {_n(missing, 'file')} had already been moved or deleted since, "
                f"so I left {had} alone.")
    return msg
