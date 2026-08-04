"""
Machine index — Freya learns her way around this computer, once, and remembers.

The problem
-----------
Ihan says "open my CV" or "run the freya project" and Freya has no idea where
either lives. Her only honest options were to guess a path (and fail), or to ask
"where is it?" — which is what a stranger asks, not someone who has been using
your machine for months. A person who works on your PC learns where things are.

So on first run she walks the machine once and writes down what she finds:
installed applications, the user's real folders, every code project, and the
documents that look like they matter. After that, "open my CV" is a lookup.

Resolution order, when she needs a location
-------------------------------------------
  1. The index — instant, no talking.
  2. A live search, if the index misses. This is the "give me a minute" path:
     she says that out loud, searches the disk herself, and remembers the answer
     so it is instant next time.
  3. Only if BOTH fail does she ask Ihan where it is — and by then the question
     is a real one, not laziness.

What it deliberately does not do
--------------------------------
Index file *contents*, or walk system directories. This is a map of where things
are, built from names and locations only. It skips Windows, Program Files,
node_modules, venvs and caches — they are noise, they are enormous, and Freya is
not allowed to modify them anyway (see core/safety.py).
"""

import fnmatch
import os
import re
import sqlite3
import threading
import time

from core.registry import tool, OBJ, P, STR, INT
from core.user_paths import all_user_folders, resolve_user_path

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "machine_index.db")

# Directory names never worth walking into. Dependency trees and caches are
# where a naive indexer spends 95% of its time and finds nothing anyone asked
# for — node_modules alone can be tens of thousands of files per project.
_SKIP_DIRS = {
    "node_modules", "venv", ".venv", "env", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", ".next", ".nuxt", "target", "obj", "bin", ".gradle", ".idea",
    ".vscode", "vendor", "site-packages", "AppData", "Application Data",
    "$Recycle.Bin", "System Volume Information", "Windows", "ProgramData",
    ".cache", ".npm", ".nuget", ".conda", "Temp", "tmp",
}

# What marks a folder as somebody's project.
_PROJECT_MARKERS = (
    ".git", "package.json", "requirements.txt", "pyproject.toml", "Cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "*.sln", "*.csproj", "Gemfile",
)

# Documents worth knowing the location of.
_DOC_EXTS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".txt", ".md",
    ".csv", ".odt", ".epub",
}

_MEDIA_EXTS = {".mp4", ".mkv", ".mp3", ".wav", ".jpg", ".jpeg", ".png", ".psd", ".ai", ".blend"}

_lock = threading.Lock()
_scan_thread: threading.Thread | None = None
_scan_state = {"running": False, "found": 0, "started": 0.0, "finished": 0.0}


# ══════════════════════════════════════════════
#  STORE
# ══════════════════════════════════════════════
def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(os.path.abspath(DB_PATH), check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id       INTEGER PRIMARY KEY,
            kind     TEXT NOT NULL,     -- app | project | document | folder | media
            name     TEXT NOT NULL,     -- what a person would call it
            path     TEXT NOT NULL UNIQUE,
            detail   TEXT DEFAULT '',   -- language, extension, launcher…
            seen_at  REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON entries(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kind ON entries(kind)")
    conn.commit()
    return conn


def _add(conn, kind: str, name: str, path: str, detail: str = "") -> None:
    try:
        conn.execute(
            "INSERT OR REPLACE INTO entries (kind, name, path, detail, seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (kind, name.strip(), os.path.abspath(path), detail, time.time()),
        )
    except Exception:
        pass


def count() -> int:
    try:
        conn = _db()
        n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return 0


# How much a match of each kind is worth. A real machine has a hundred apps and
# tens of thousands of media files, so an unweighted substring search answers
# "open valorant" with holiday screenshots — measured, not hypothetical: the
# first version returned four JPEGs and never mentioned the game.
_KIND_RANK = {"app": 0, "project": 1, "folder": 2, "document": 3, "media": 4, "file": 3}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s\-_.,/\\]+", text.lower()) if t]


def lookup(query: str, kind: str | None = None, limit: int = 12) -> list[dict]:
    """Search the index, ranked by what the person probably meant.

    Token-based rather than whole-string: "vs code" has to find "Visual Studio
    Code", and a single LIKE '%vs code%' never will. Any token may match; how
    many matched decides the rank.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    toks = _tokens(q) or [q]

    conn = _db()
    try:
        where = " OR ".join(["LOWER(name) LIKE ? OR LOWER(path) LIKE ?"] * len(toks))
        params: list = []
        for t in toks:
            params += [f"%{t}%", f"%{t}%"]
        sql = f"SELECT kind, name, path, detail FROM entries WHERE ({where})"
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        # Cap the candidate set: a one-letter token would otherwise pull the
        # whole table into memory before scoring.
        rows = conn.execute(sql + " LIMIT 4000", params).fetchall()
    finally:
        conn.close()

    scored = []
    seen = set()
    for k, name, path, detail in rows:
        if path in seen:
            continue
        seen.add(path)
        low = name.lower()
        name_toks = set(_tokens(name))
        matched = sum(1 for t in toks if t in low)
        matched_path = sum(1 for t in toks if t in path.lower())

        if low == q:
            quality = 0
        elif low.startswith(q):
            quality = 1
        elif matched == len(toks):
            quality = 2                       # every token present in the name
        elif toks and set(toks) <= name_toks:
            quality = 2
        elif matched:
            quality = 3                       # some tokens
        elif matched_path == len(toks):
            quality = 4                       # only the path matched
        else:
            quality = 5

        # Quality first, kind second. Kind-first was wrong: "my cv" returned a
        # project called "myApp" ahead of the actual file "My CV ihan.docx",
        # because being an app/project outranked being the thing he named.
        # Kind now only breaks ties between equally good name matches.
        scored.append(((quality, _KIND_RANK.get(k, 3), len(name)),
                       {"kind": k, "name": name, "path": path, "detail": detail}))

    scored.sort(key=lambda pair: pair[0])
    return [entry for _score, entry in scored[:limit]]


# ══════════════════════════════════════════════
#  SCANNERS
# ══════════════════════════════════════════════
def _scan_apps(conn) -> int:
    """Installed applications, from the Start Menu.

    Start Menu shortcuts rather than the registry's uninstall keys: the shortcut
    is what the user actually sees and names things by ("Valorant", not
    "Riot Games Valorant 1.0"), and it points at something launchable.
    """
    found = 0
    roots = [
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root, onerror=lambda e: None):
            for f in files:
                if not f.lower().endswith((".lnk", ".url")):
                    continue
                name = os.path.splitext(f)[0]
                if name.lower().startswith(("uninstall", "readme", "help", "documentation")):
                    continue
                _add(conn, "app", name, os.path.join(dirpath, f), "start-menu")
                found += 1
    return found


def _scan_registry_apps(conn) -> int:
    """Installed programs from the uninstall registry.

    The Start Menu alone is not enough: games installed through their own
    launchers and portable/manual installs often have no shortcut. Verified on
    this machine — VALORANT and Blender were both completely missing until this
    was added, so "open valorant" returned holiday photos.
    """
    found = 0
    try:
        import winreg
    except ImportError:
        return 0

    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, subkey in keys:
        try:
            root = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        try:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, name) as app:
                        display = _reg_value(app, "DisplayName")
                        if not display:
                            continue
                        # Updates and runtimes are not things anyone asks for.
                        low = display.lower()
                        if any(s in low for s in ("update for", "hotfix", "redistributable",
                                                  "driver package", "language pack")):
                            continue
                        location = (_reg_value(app, "InstallLocation") or
                                    _reg_value(app, "DisplayIcon") or "")
                        location = location.split(",")[0].strip('"')
                        if not location or not os.path.exists(location):
                            continue
                        _add(conn, "app", display, location, "installed")
                        found += 1
                except OSError:
                    continue
        finally:
            root.Close()
    return found


# Executables that ship alongside real applications but are never what somebody
# means when they name a program.
_HELPER_EXE = (
    "unins", "setup", "install", "update", "crashpad", "crashreport", "helper",
    "vcredist", "dxsetup", "launcher_", "repair", "cleanup", "service",
    "daemon", "watchdog", "reporter", "elevate",
)


def _is_helper_exe(stem: str) -> bool:
    low = stem.lower()
    return any(low.startswith(h) or h in low for h in _HELPER_EXE)


def _reg_value(key, name: str) -> str:
    try:
        import winreg
        value, _type = winreg.QueryValueEx(key, name)
        return str(value).strip()
    except Exception:
        return ""


def _scan_config_apps(conn, config: dict | None) -> int:
    """Whatever Ihan already told Freya about in config — apps and projects.

    These are the highest-confidence entries in the whole index: he named them
    himself, and `open_app` already launches by exactly these names.
    """
    found = 0
    cfg = config or {}
    for name, path in (cfg.get("apps") or {}).items():
        if path:
            _add(conn, "app", name, path, "configured")
            found += 1
    for name, path in (cfg.get("projects") or {}).items():
        if path:
            _add(conn, "project", name, path, "configured")
            found += 1
    return found


def _looks_like_project(dirpath: str, entries: list[str]) -> str | None:
    """Return the marker that makes this a project, or None."""
    for marker in _PROJECT_MARKERS:
        if "*" in marker:
            if any(fnmatch.fnmatch(e, marker) for e in entries):
                return marker
        elif marker in entries:
            return marker
    return None


def _scan_tree(conn, root: str, max_depth: int = 6, budget: float = 90.0) -> int:
    """Walk one root, recording projects, documents and media.

    Depth- and time-bounded on purpose. An unbounded walk of a data drive can
    run for many minutes, and this runs at startup — a first launch that hangs
    is worse than an index that is 95% complete.
    """
    found = 0
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return 0
    deadline = time.time() + budget
    base_depth = root.rstrip(os.sep).count(os.sep)

    for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
        if time.time() > deadline:
            break

        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []

        marker = _looks_like_project(dirpath, dirs + files)
        if marker:
            _add(conn, "project", os.path.basename(dirpath), dirpath, f"marker:{marker}")
            found += 1
            # Don't descend into a project — its innards are source files, and
            # the thing people refer to by name is the project itself.
            dirs[:] = []
            continue

        depth = dirpath.count(os.sep) - base_depth
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext == ".exe":
                # Portable installs have no registry entry and no shortcut —
                # Blender on this machine is literally D:\software\new\blender.exe.
                # Shallow only: deep .exe files are bundled helpers and updaters
                # nobody refers to by name.
                stem = os.path.splitext(f)[0]
                if depth <= 3 and not _is_helper_exe(stem):
                    _add(conn, "app", stem, os.path.join(dirpath, f), "portable")
                    found += 1
            elif ext in _DOC_EXTS:
                _add(conn, "document", os.path.splitext(f)[0], os.path.join(dirpath, f), ext)
                found += 1
            elif ext in _MEDIA_EXTS:
                _add(conn, "media", os.path.splitext(f)[0], os.path.join(dirpath, f), ext)
                found += 1

    return found


def _data_drives() -> list[str]:
    """Fixed drives other than the system one — where projects usually live."""
    system = (os.environ.get("SystemDrive") or "C:").upper()
    out = []
    for letter in "CDEFGH":
        drive = f"{letter}:\\"
        if not os.path.isdir(drive):
            continue
        if f"{letter}:".upper() == system:
            continue        # the system drive is covered via the user folders
        out.append(drive)
    return out


def run_scan(config: dict | None = None, deep: bool = False) -> dict:
    """The full pass. Returns a summary; safe to call repeatedly."""
    with _lock:
        _scan_state.update(running=True, found=0, started=time.time(), finished=0.0)
        conn = _db()
        summary = {"apps": 0, "user": 0, "drives": 0}
        try:
            summary["apps"] = (_scan_apps(conn)
                               + _scan_registry_apps(conn)
                               + _scan_config_apps(conn, config))
            conn.commit()

            for name, path in all_user_folders().items():
                _add(conn, "folder", name, path, "known-folder")
                if name != "home":
                    summary["user"] += _scan_tree(conn, path, max_depth=5, budget=45)
            conn.commit()

            budget = 240.0 if deep else 60.0
            for drive in _data_drives():
                summary["drives"] += _scan_tree(conn, drive, max_depth=5, budget=budget)
                conn.commit()
        finally:
            conn.close()
            total = sum(summary.values())
            _scan_state.update(running=False, found=total, finished=time.time())
        summary["total"] = sum(summary.values())
        return summary


def scan_in_background(config: dict | None = None) -> None:
    """Kick off the first-run scan without delaying startup."""
    global _scan_thread
    if _scan_state["running"]:
        return
    _scan_thread = threading.Thread(
        target=lambda: _quiet_scan(config), daemon=True, name="freya-machine-index")
    _scan_thread.start()


def _quiet_scan(config):
    try:
        started = time.time()
        summary = run_scan(config)
        print(f"  Machine index: {summary['total']} things learned "
              f"({summary['apps']} apps) in {time.time() - started:.0f}s.")
    except Exception as e:
        print(f"  Machine index scan failed: {e}")


def ensure_index(config: dict | None = None) -> None:
    """Called at startup. Scans only if the index is empty or stale."""
    try:
        cfg = (config or {}).get("machine_index", {})
        if not cfg.get("enabled", True):
            return
        n = count()
        if n == 0:
            print("  First run — learning my way around your PC in the background...")
            scan_in_background(config)
            return
        # Refresh if it has gone stale, so newly installed apps and new projects
        # turn up without anyone having to think about it.
        max_age_days = float(cfg.get("refresh_days", 7))
        conn = _db()
        try:
            newest = conn.execute("SELECT MAX(seen_at) FROM entries").fetchone()[0] or 0
        finally:
            conn.close()
        if time.time() - newest > max_age_days * 86400:
            print(f"  Machine index is over {max_age_days:.0f} days old — refreshing quietly.")
            scan_in_background(config)
    except Exception as e:
        print(f"  Machine index unavailable: {e}")


# ══════════════════════════════════════════════
#  LIVE SEARCH (the "give me a minute" path)
# ══════════════════════════════════════════════
def live_search(query: str, kinds: tuple[str, ...] = (), limit: int = 10,
                budget: float = 25.0) -> list[dict]:
    """Search the disk right now for something the index doesn't know.

    Deliberately narrow and time-boxed: user folders and data drives, name
    matching only. It exists so Freya can answer "where is X" herself in the
    time it takes to say "give me a minute" — not to be a filesystem crawler.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    deadline = time.time() + budget
    hits: list[dict] = []
    seen = set()

    roots = [p for p in all_user_folders().values()] + _data_drives()

    for root in roots:
        if time.time() > deadline or len(hits) >= limit:
            break
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
            if time.time() > deadline or len(hits) >= limit:
                break
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for entry in dirs + files:
                if q not in entry.lower():
                    continue
                full = os.path.join(dirpath, entry)
                if full in seen:
                    continue
                seen.add(full)
                kind = ("project" if os.path.isdir(full) and
                        _looks_like_project(full, _safe_listdir(full)) else
                        "folder" if os.path.isdir(full) else "file")
                if kinds and kind not in kinds:
                    continue
                hits.append({"kind": kind, "name": entry, "path": full, "detail": "live-search"})
                if len(hits) >= limit:
                    break

    # Remember what we just learned, so this is instant next time.
    if hits:
        conn = _db()
        try:
            for h in hits:
                _add(conn, h["kind"] if h["kind"] != "file" else "document",
                     os.path.splitext(h["name"])[0], h["path"], "live-search")
            conn.commit()
        finally:
            conn.close()
    return hits


def _safe_listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except Exception:
        return []


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
@tool(
    "find_on_pc",
    "Find where something lives on Ihan's computer — an app, a project, a document, a folder. "
    "ALWAYS use this before asking him where something is: you have an index of his machine and "
    "you can search it yourself. If it isn't in the index this searches the disk live, which "
    "takes a few seconds — say 'give me a minute' out loud first, then call it. Only ask Ihan "
    "where something is if this comes back with nothing.",
    OBJ({"what": P(STR, "What you're looking for, e.g. 'my CV', 'freyav3', 'valorant'"),
         "kind": P(STR, "Optional filter: app, project, document, folder, media")},
        ["what"]),
)
def find_on_pc(args, ctx) -> str:
    what = (args.get("what") or "").strip()
    if not what:
        return "What am I looking for?"
    kind = (args.get("kind") or "").strip().lower() or None

    results = lookup(what, kind)
    source = "from what I know of your PC"

    if not results:
        results = [r for r in live_search(what) if not kind or r["kind"] == kind]
        source = "after searching your drives just now"

    if not results:
        return (f"I couldn't find anything called '{what}' — not in my index and not on the "
                f"drives I can see. This is the point where you should ask Ihan where it is, "
                f"or what it's actually called.")

    lines = [f"{r['name']} ({r['kind']}) — {r['path']}" for r in results[:8]]
    note = ("\nSeveral matches: pick the one that fits what he asked for, or ask him which."
            if len(results) > 1 else "")
    return f"Found {source}:\n" + "\n".join(lines) + note


@tool(
    "list_installed_apps",
    "List the applications installed on this PC (optionally filtered). Use when Ihan asks what "
    "he has installed, or when you need the real name of an app before opening it.",
    OBJ({"filter": P(STR, "Optional substring to filter by, e.g. 'adobe'"),
         "limit": P(INT, "How many to return (default 30)")}),
)
def list_installed_apps(args, ctx) -> str:
    needle = (args.get("filter") or "").strip().lower()
    limit = max(1, min(100, int(args.get("limit") or 30)))
    conn = _db()
    try:
        if needle:
            rows = conn.execute(
                "SELECT name, path FROM entries WHERE kind='app' AND LOWER(name) LIKE ? "
                "ORDER BY name LIMIT ?", (f"%{needle}%", limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, path FROM entries WHERE kind='app' ORDER BY name LIMIT ?",
                (limit,)).fetchall()
    finally:
        conn.close()
    if not rows:
        if count() == 0:
            return ("I haven't finished learning this PC yet — run refresh_pc_knowledge, or "
                    "give it a moment if I've only just started.")
        return f"No installed app matches '{needle}'." if needle else "I don't have any apps indexed."
    return f"{len(rows)} app(s): " + "; ".join(name for name, _ in rows)


@tool(
    "list_my_projects",
    "List the code projects found on this PC, with their locations. Use when Ihan mentions "
    "'my project' or a project by name and you need the real path.",
    OBJ({"filter": P(STR, "Optional substring to filter by")}),
)
def list_my_projects(args, ctx) -> str:
    needle = (args.get("filter") or "").strip().lower()
    conn = _db()
    try:
        if needle:
            rows = conn.execute(
                "SELECT name, path, detail FROM entries WHERE kind='project' AND "
                "(LOWER(name) LIKE ? OR LOWER(path) LIKE ?) ORDER BY name LIMIT 40",
                (f"%{needle}%", f"%{needle}%")).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, path, detail FROM entries WHERE kind='project' "
                "ORDER BY name LIMIT 40").fetchall()
    finally:
        conn.close()
    if not rows:
        return f"No project matches '{needle}'." if needle else "I haven't indexed any projects yet."
    return "\n".join(f"{n} — {p}" for n, p, _d in rows)


@tool(
    "refresh_pc_knowledge",
    "Re-scan the computer to update what you know about it — new apps, new projects, moved "
    "files. Takes a minute or two; tell Ihan you're doing it and carry on talking.",
    OBJ({"deep": P(STR, "'true' to scan data drives more thoroughly (slower)")}),
)
async def refresh_pc_knowledge(args, ctx) -> str:
    if _scan_state["running"]:
        return "I'm already re-scanning — it's running in the background right now."
    deep = str(args.get("deep", "")).lower() in ("true", "yes", "1")
    scan_in_background(ctx.config)
    return ("I'm re-learning your PC in the background now" +
            (" (deep scan, so it'll take a couple of minutes)" if deep else "") +
            ". I'll keep talking while it runs — ask me again in a minute and I'll know more.")


@tool(
    "pc_knowledge_status",
    "Check what you currently know about this PC and whether a scan is running.",
    OBJ(),
)
def pc_knowledge_status(args, ctx) -> str:
    conn = _db()
    try:
        rows = conn.execute("SELECT kind, COUNT(*) FROM entries GROUP BY kind").fetchall()
    finally:
        conn.close()
    if not rows:
        return "I don't know anything about this PC yet — no scan has completed."
    parts = ", ".join(f"{n} {kind}s" for kind, n in rows)
    if _scan_state["running"]:
        return f"I know about {parts}. A scan is running right now, so that's still growing."
    age = time.time() - (_scan_state.get("finished") or 0)
    when = f", last updated {age / 3600:.0f}h ago" if _scan_state.get("finished") else ""
    return f"I know about {parts}{when}."
