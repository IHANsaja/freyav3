"""
Tests for the file-search fixes: tokenised live_search, a candidate cap that
can't be swamped by media rows, and a search_files that stops on a clock.

    venv\\Scripts\\python.exe test_scripts\\test_search.py

The live_search test writes a throwaway file under the user's Documents folder
(and deletes it again) because live_search only walks the known user folders and
data drives — a file in %TEMP% would never be reachable.
"""

import asyncio
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import machine_index
from core.machine_index import _tokens, live_search, lookup
from core.registry import ToolContext, dispatch
from core.user_paths import user_folder

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        raise AssertionError(f"{label} {detail}".strip())


async def main() -> None:
    with open(os.path.join(PROJECT_ROOT, "config", "freya_config.json"),
              "r", encoding="utf-8") as f:
        cfg = json.load(f)
    ctx = ToolContext(cfg, session=None)

    # ── 1. the index still answers multi-word app queries ─────────────────
    print("\n[1] lookup() ranking")
    hits = lookup("vs code", kind="app")
    print("      " + "; ".join(f"{h['name']}" for h in hits[:4]))
    check("finds Visual Studio Code for 'vs code'",
          any("code" in h["name"].lower() for h in hits), str(hits[:2]))

    media = [h for h in lookup("screenshot")[:12] if h["kind"] == "media"]
    apps = lookup("blender", kind="app")
    print(f"      'blender' as app -> {[h['name'] for h in apps[:3]]}")
    check("kind-ordered candidate cap still returns apps for an app query",
          apps == [] or apps[0]["kind"] == "app")
    print(f"      ('screenshot' returns {len(media)} media rows — expected, it's a media word)")

    # ── 2. live_search handles a two-word query ───────────────────────────
    print("\n[2] live_search tokenisation")
    check("the old whole-string test would have failed",
          "my testfile" not in "freya my-testfile marker.txt".lower())
    check("the tokenised test passes",
          all(t in "freya my-testfile marker.txt" for t in _tokens("my testfile")))

    docs = user_folder("documents")
    probe_dir = os.path.join(docs, "_freya_search_probe")
    probe = os.path.join(probe_dir, "freya my-testfile marker.txt")
    try:
        os.makedirs(probe_dir, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("probe")
        hits = live_search("my testfile", budget=20.0)
        print(f"      {[h['path'] for h in hits[:3]]}")
        check("live_search finds a two-word filename",
              any(os.path.normcase(h["path"]) == os.path.normcase(probe) for h in hits),
              f"got {hits[:3]}")
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
        # live_search writes its hits into the index — take the probe back out.
        try:
            conn = machine_index._db()
            conn.execute("DELETE FROM entries WHERE path LIKE ?", (f"{probe_dir}%",))
            conn.commit()
            conn.close()
        except Exception:
            pass

    # ── 3. search_files stops on a clock ──────────────────────────────────
    print("\n[3] search_files budget")
    started = time.time()
    out = await dispatch("search_files", {"directory": PROJECT_ROOT, "pattern": "*.py"}, ctx)
    elapsed = time.time() - started
    print(f"      {elapsed:.1f}s — {out[:140]}")
    check("finds project .py files", "match(es)" in out)
    check("skips venv/ (would otherwise dominate the hits)",
          "venv" not in out.lower(), out[:200])

    started = time.time()
    out = await dispatch("search_files",
                         {"directory": user_folder("home"), "pattern": "*.zzznope"}, ctx)
    elapsed = time.time() - started
    print(f"      whole-home miss took {elapsed:.1f}s")
    check(f"a hopeless search returns within its budget ({elapsed:.0f}s)",
          elapsed < 40, f"{elapsed:.1f}s")

    # Force the deadline branch: home is fast enough that the real budget never
    # trips, so squeeze it to zero and confirm she says she ran out of time
    # rather than reporting a clean "nothing there".
    from core import system_tools
    original = system_tools.SEARCH_BUDGET_S
    try:
        system_tools.SEARCH_BUDGET_S = 0.0
        out = await dispatch("search_files",
                             {"directory": user_folder("home"), "pattern": "*.zzznope"}, ctx)
    finally:
        system_tools.SEARCH_BUDGET_S = original
    print(f"      zero-budget: {out[:120]}")
    check("says it ran out of time instead of 'nothing there'", "ran out of time" in out)

    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
