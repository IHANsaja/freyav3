"""
Round-trip test for core/organizer.py — tidy a throwaway folder, then undo it and
prove the folder is byte-for-byte back where it started. Run from the project root:

    venv\\Scripts\\python.exe test_scripts\\test_organizer.py

Goes through registry.dispatch rather than calling the handlers directly, so the
safety gate in core/safety.py is exercised too — that's the half most likely to
be mis-wired (a tool missing from _PATH_ARGS fails silently open).
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import organizer
from core.registry import ToolContext, dispatch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FILES = {
    "holiday.png": "img", "screenshot.jpg": "img", "meme.gif": "img",
    "invoice.pdf": "doc", "notes.txt": "doc",
    "setup.exe": "bin", "driver.msi": "bin",
    "backup.zip": "zip",          # lone archive — must stay put (min_group)
    "Chrome.lnk": "shortcut",     # must never move
    ".env": "hidden",             # dotfile — must never move
}


def snapshot(root: str) -> dict:
    """{relative path: size} for everything under root."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            full = os.path.join(dirpath, f)
            out[os.path.relpath(full, root)] = os.path.getsize(full)
    return out


def build(root: str) -> None:
    for name, body in FILES.items():
        with open(os.path.join(root, name), "w", encoding="utf-8") as f:
            f.write(body)
    # A git checkout sitting on the desktop — somebody's work, must be left alone.
    os.makedirs(os.path.join(root, "myrepo", ".git"), exist_ok=True)
    with open(os.path.join(root, "myrepo", "main.py"), "w", encoding="utf-8") as f:
        f.write("print('hi')")
    # An ordinary folder — skipped because include_folders defaults to false.
    os.makedirs(os.path.join(root, "notes"), exist_ok=True)


def check(label: str, condition: bool) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        raise AssertionError(label)


async def main() -> None:
    with open(os.path.join(PROJECT_ROOT, "config", "freya_config.json"),
              "r", encoding="utf-8") as f:
        cfg = json.load(f)
    ctx = ToolContext(cfg, session=None)

    tmp = tempfile.mkdtemp(prefix="freya_tidy_")
    # Keep the real undo manifest out of this — and keep the test manifest out
    # of `tmp`, or it shows up in the snapshot and the round-trip never matches.
    state = tempfile.mkdtemp(prefix="freya_tidy_state_")
    organizer._MANIFEST = os.path.join(state, "manifest.json")

    try:
        build(tmp)
        before = snapshot(tmp)
        print(f"\n[setup] {tmp} — {len(before)} files\n")

        # ── 1. dry run changes nothing ────────────────────────────────────
        print("[1] dry run")
        out = await dispatch("organize_folder", {"folder": tmp, "dry_run": True}, ctx)
        print(f"      {out[:160]}")
        check("nothing moved", snapshot(tmp) == before)

        # ── 2. the real thing ─────────────────────────────────────────────
        print("[2] organize")
        out = await dispatch("organize_folder", {"folder": tmp}, ctx)
        print(f"      {out[:200]}")
        at = lambda *p: os.path.join(tmp, *p)
        check("Images/ has 3", len(os.listdir(at("Images"))) == 3)
        check("Documents/ has 2", len(os.listdir(at("Documents"))) == 2)
        check("Installers/ has 2", len(os.listdir(at("Installers"))) == 2)
        check("no Archives/ for a lone zip", not os.path.exists(at("Archives")))
        check("backup.zip stayed put", os.path.isfile(at("backup.zip")))
        check("Chrome.lnk stayed put", os.path.isfile(at("Chrome.lnk")))
        check(".env stayed put", os.path.isfile(at(".env")))
        check("myrepo/ untouched", os.path.isfile(at("myrepo", "main.py")))
        check("notes/ untouched", os.path.isdir(at("notes")))

        # ── 3. re-running is a no-op, and doesn't clobber the undo record ──
        print("[3] re-run (idempotence)")
        out = await dispatch("organize_folder", {"folder": tmp}, ctx)
        print(f"      {out[:120]}")
        check("no nested Images/Images", not os.path.exists(at("Images", "Images")))
        check("second run reports nothing to do", "already sorted" in out)

        # ── 4. undo restores the original layout exactly ──────────────────
        print("[4] undo")
        out = await dispatch("undo_organize", {"folder": tmp}, ctx)
        print(f"      {out[:160]}")
        check("folder is byte-for-byte as it started", snapshot(tmp) == before)
        check("Images/ removed", not os.path.exists(at("Images")))
        check("Documents/ removed", not os.path.exists(at("Documents")))
        check("Installers/ removed", not os.path.exists(at("Installers")))

        # ── 5. the safety gate refuses to reorganize a repo ───────────────
        print("[5] safety gate")
        out = await dispatch("organize_folder", {"folder": PROJECT_ROOT}, ctx)
        print(f"      {out[:160]}")
        check("refuses the Freya repo", "won't delete or move" in out)
        check("repo untouched", os.path.isfile(os.path.join(PROJECT_ROOT, "main.py")))

        print("\nAll checks passed.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
