"""
Pre-release smoke test — boots everything except the audio/Gemini session and
exercises the whole read-only tool surface. Run from the project root:

    venv\\Scripts\\python.exe test_scripts\\test_smoke.py

This is the "does a fresh clone actually work" check: config loads, every skill
imports, every declared tool is dispatchable, nothing that should be free asks
for approval, and the safety gate still refuses the things it must refuse.

Deliberately read-only. It never launches an app, writes outside a temp dir, or
touches the network.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(f"{label} {detail}".strip())


async def main() -> None:
    # ── 1. config ─────────────────────────────────────────────────────────
    print("\n[1] config")
    from config import load_config, CONFIG_PATH, EXAMPLE_CONFIG_PATH
    cfg = load_config()
    check("config loads", isinstance(cfg, dict) and "freya" in cfg)
    check("example template is present for fresh clones", os.path.exists(EXAMPLE_CONFIG_PATH))
    with open(EXAMPLE_CONFIG_PATH, encoding="utf-8") as f:
        example = json.load(f)
    check("example carries no personal app paths", not example.get("apps"))
    check("example carries no personal projects", not example.get("projects"))
    live = json.dumps(cfg)
    check("live config has no dead app paths",
          all(os.path.exists(p) for p in (cfg.get("apps") or {}).values()),
          str([k for k, p in (cfg.get("apps") or {}).items() if not os.path.exists(p)]))

    # ── 2. skills + registry ──────────────────────────────────────────────
    print("\n[2] skills and registry")
    from core.skills.loader import load_all
    from core.registry import build_declarations, _REGISTRY
    from core.model import TOOL_DECLARATIONS
    manifests = load_all()
    check(f"all skills import ({len(manifests)} loaded)", len(manifests) >= 20)
    decls = build_declarations(cfg)
    names = [d.name for d in TOOL_DECLARATIONS] + [d.name for d in decls]
    dupes = sorted({n for n in names if names.count(n) > 1})
    check(f"no duplicate declarations ({len(names)} tools)", not dupes, str(dupes))

    # Every declared tool must be dispatchable — a declaration with no handler
    # is a tool the model will confidently call and get an error from.
    legacy = set()
    try:
        import core.tools as legacy_mod
        import inspect
        legacy = set(re.findall(r'name == "(\w+)"', inspect.getsource(legacy_mod.dispatch)))
    except Exception:
        pass
    orphans = [n for n in names if n not in _REGISTRY and n not in legacy]
    check("every declared tool has a handler", not orphans, str(orphans))

    # ── 3. the tools this release is about ────────────────────────────────
    print("\n[3] new capabilities are wired")
    for name in ("organize_folder", "undo_organize", "get_active_window",
                 "list_windows", "open_app", "find_on_pc", "search_files"):
        check(f"{name} declared", name in names)

    # ── 4. approval policy ────────────────────────────────────────────────
    print("\n[4] approval policy")
    from core.safety import needs_approval
    free = ("get_active_window", "list_windows", "open_app", "find_on_pc",
            "search_files", "organize_folder", "undo_organize", "read_file", "list_dir")
    for name in free:
        check(f"{name} needs no approval",
              not needs_approval(name, {"name": "x", "what": "x", "folder": "desktop"},
                                 _REGISTRY.get(name), cfg))
    gated = ("delete_item", "shutdown_computer")
    for name in gated:
        check(f"{name} still asks first",
              needs_approval(name, {"path": "x"}, _REGISTRY.get(name), cfg))

    # ── 5. safety gate still refuses the important things ─────────────────
    print("\n[5] safety gate")
    from core.registry import ToolContext, dispatch
    ctx = ToolContext(cfg, session=None)
    win = os.environ.get("SystemRoot", r"C:\Windows")
    out = await dispatch("write_file", {"path": os.path.join(win, "freya_test.txt"),
                                        "content": "x"}, ctx)
    check("refuses to write into Windows", "part of Windows" in out, out[:90])
    out = await dispatch("organize_folder", {"folder": PROJECT_ROOT}, ctx)
    check("refuses to reorganize a repo", "won't delete or move" in out, out[:90])
    out = await dispatch("move_item", {"source": PROJECT_ROOT, "destination": "D:/x"}, ctx)
    check("refuses to move a repo", "won't delete or move" in out, out[:90])

    # ── 6. read-only tools actually return something sane ─────────────────
    print("\n[6] live tool calls")
    probes = [
        ("get_user_folders", {}, "desktop"),
        ("list_dir", {"path": "desktop"}, ""),
        ("get_active_window", {}, ""),
        ("list_windows", {}, ""),
        ("pc_knowledge_status", {}, "Indexed"),
        ("find_on_pc", {"what": "freyav3"}, "freyav3"),
        ("list_skills", {}, ""),
    ]
    for name, args, expect in probes:
        out = str(await dispatch(name, args, ctx))
        ok = bool(out.strip()) and "Tool error" not in out and expect.lower() in out.lower()
        check(f"{name} returns usable output", ok, out[:100])

    print("\n" + ("=" * 60))
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All smoke checks passed.")


if __name__ == "__main__":
    import re  # used in the orphan scan above
    asyncio.run(main())
