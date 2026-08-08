"""
Smoke test for Freya's PC awareness — what's open, what's in front, and whether
open_app is declared honestly. Run from the project root:

    venv\\Scripts\\python.exe test_scripts\\test_awareness.py

Goes through registry.dispatch, so gates and the safety guard are exercised the
same way the live model hits them. Nothing here launches or closes anything.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.model import TOOL_DECLARATIONS
from core.registry import ToolContext, build_declarations, dispatch

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

    # ── 1. no duplicate declarations ──────────────────────────────────────
    print("\n[1] tool declarations")
    names = [d.name for d in TOOL_DECLARATIONS] + [d.name for d in build_declarations(cfg)]
    dupes = {n for n in names if names.count(n) > 1}
    check(f"no duplicate tool names ({len(names)} declared)", not dupes, str(dupes))
    check("open_app is declared exactly once", names.count("open_app") == 1)
    check("get_active_window is declared", "get_active_window" in names)

    decl = next(d for d in build_declarations(cfg) if d.name == "open_app")
    check("open_app no longer advertises only the config keys",
          "photoshop, discord, steam" not in decl.description)
    check("open_app tells the model not to ask for a path",
          "never ask" in decl.description.lower())

    # ── 2. the focused window ─────────────────────────────────────────────
    print("\n[2] get_active_window")
    out = await dispatch("get_active_window", {}, ctx)
    print(f"      {out}")
    check("names something", bool(out.strip()))
    check("isn't an error", "error" not in out.lower() and "traceback" not in out.lower())

    # ── 3. what's open ────────────────────────────────────────────────────
    print("\n[3] list_windows")
    windows = await dispatch("list_windows", {}, ctx)
    print("      " + windows.replace("\n", "\n      ")[:600])
    check("reports open programs", "program(s) open" in windows or "Nothing's open" in windows)
    check("marks which one is in front", "in front" in windows)

    print("\n[4] list_windows(include_background=True)")
    full = await dispatch("list_windows", {"include_background": True}, ctx)
    print("      …" + full[-300:].replace("\n", "\n      "))
    check("adds the background section", "without a window" in full)
    check("is strictly longer than the window list", len(full) > len(windows))

    # ── 5. nothing here should need approval ──────────────────────────────
    print("\n[5] no approval gates")
    from core.safety import needs_approval
    from core.registry import _REGISTRY
    for name in ("get_active_window", "list_windows", "open_app", "find_on_pc",
                 "search_files"):
        entry = _REGISTRY.get(name)
        check(f"{name} runs without a prompt",
              not needs_approval(name, {"name": "x", "what": "x"}, entry, cfg))

    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
