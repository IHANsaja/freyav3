"""
Offline smoke test for Freya's superpowers — exercises the registry + a few safe tools
WITHOUT opening the Gemini Live audio session. Run from the project root:

    venv\\Scripts\\python.exe test_scripts\\test_superpowers.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.registry import build_declarations, dispatch, ToolContext, registered_names


def load_cfg():
    with open("config/freya_config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("rag", {})["enabled"] = True
    return cfg


async def main():
    cfg = load_cfg()
    ctx = ToolContext(cfg, session=None)

    decls = build_declarations(cfg)
    print(f"[registry] new declarations: {len(decls)}  | total handlers: {len(registered_names())}")
    assert len(decls) >= 30, "expected 30+ new tools"

    async def run(name, args):
        print(f"\n--- {name}({args}) ---")
        try:
            out = await dispatch(name, args, ctx)
            print(str(out)[:400])
            return out
        except Exception as e:
            print(f"ERROR: {e}")
            return None

    # 1) Real world news (network, no key)
    await run("get_world_news", {})

    # 2) Clipboard round-trip (offline)
    await run("clipboard_write", {"text": "Freya superpowers online."})
    await run("clipboard_read", {})

    # 3) Pixel-perfect screen scan (UI Automation, offline)
    await run("read_screen_elements", {})

    # 4) Filesystem listing (offline, safe)
    await run("list_dir", {"path": "."})

    # 5) Self-extension code run (guarded subprocess)
    await run("run_code", {"code": "print(6*7)"})

    # 6) Semantic recall (needs embeddings API key; tolerated if offline)
    await run("recall", {"query": "what do you know about Ihan"})

    # 7) Safety gate refuses a destructive command
    res = await run("run_terminal_command", {"command": "rm -rf /"})
    assert res and "won't" in str(res).lower(), "safety gate should refuse rm -rf"

    print("\n[OK] superpower smoke test complete.")


if __name__ == "__main__":
    asyncio.run(main())
