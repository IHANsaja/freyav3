"""
Skill loader — makes capabilities first-class, discoverable modules.

A skill is a Python module that registers tools via `core.registry`. It may declare
a `SKILL = SkillManifest(...)` at module level; modules without one get an
auto-generated manifest so every existing skill keeps working unchanged.

The loader replaces the hardcoded import list that used to live in
`registry._load_skills()`. While each module imports, `registry._current_skill`
is set so `register()` stamps every tool with its owning skill id — that's what
powers the skill catalog (GET /skills) and per-skill enable toggles.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SkillManifest:
    id: str
    name: str
    description: str
    gate: Optional[str] = None  # config path that enables/disables the skill
    version: str = "1.0"


# Built-in skills: (module path, fallback manifest). The fallback is used when
# the module doesn't define its own SKILL constant.
BUILTIN_SKILLS: list[tuple[str, SkillManifest]] = [
    ("core.approvals", SkillManifest("approvals", "Approval Gate",
     "Human-in-the-loop confirmation for sensitive actions")),
    ("core.avatar", SkillManifest("avatar", "Avatar Animator",
     "Expressions, gestures and poses for Freya's 3D body")),
    ("core.news", SkillManifest("news", "News",
     "World and topic headlines, read aloud with dashboard cards")),
    ("core.system_tools", SkillManifest("system", "System Control",
     "Clipboard, files, windows, volume and media control")),
    ("core.file_manager", SkillManifest("files", "File Manager",
     "Copy, move, rename, recycle, zip and inspect files and folders")),
    ("core.screen", SkillManifest("screen", "Screen Control",
     "Read and operate on-screen UI elements via Windows accessibility", gate="screen.engine")),
    ("core.agents", SkillManifest("agents", "Sub-Agents",
     "Background researcher / coder / operator delegation")),
    ("core.missions", SkillManifest("missions", "Missions",
     "Plan → execute → verify orchestration for big goals")),
    ("core.browser_agent", SkillManifest("browser", "Browser Operator",
     "Human-like Chromium browsing: DuckDuckGo search, real clicks and reading",
     gate="browser.enabled")),
    ("core.rag_memory", SkillManifest("rag", "Semantic Recall",
     "Vector search over memory and indexed documents", gate="rag.enabled")),
    ("core.memory_tools", SkillManifest("memory", "Structured Memory",
     "Remember, recall, edit and forget typed memory items")),
    ("core.scheduler", SkillManifest("scheduler", "Scheduler",
     "Spoken reminders, recurring tasks and briefings", gate="scheduler.enabled")),
    ("core.ambient", SkillManifest("ambient", "Ambient Watcher",
     "Watch the screen for a condition and alert proactively", gate="ambient.enabled")),
    ("core.context_watch", SkillManifest("context", "Context Awareness",
     "Always-on window tracking with proactive suggestions")),
    ("core.self_extend", SkillManifest("self_extend", "Self-Extension",
     "Freya writes and hot-loads new tools for herself")),
    ("core.listening_tools", SkillManifest("listening", "Listening Control",
     "Pause/resume the microphone by voice")),
    ("core.web", SkillManifest("web", "Web Search",
     "Quota-free web search and page fetching")),
    ("core.machine_index", SkillManifest("machine", "PC Knowledge",
     "Knows where apps, projects and documents live on this computer",
     gate="machine_index.enabled")),
    ("core.md_skills", SkillManifest("md_skills", "Skill Packs",
     "Claude-style SKILL.md capability packs loaded on demand")),
    ("core.career_ops", SkillManifest("career", "Career Ops",
     "Job search: portal scanning, A-G offer evaluation, CV tailoring and tracking")),
]

_manifests: dict[str, SkillManifest] = {}


def load_all() -> dict[str, SkillManifest]:
    """Import every builtin skill + hot-loaded custom tools, stamping each
    registered tool with its skill id. Idempotent."""
    from core import registry

    if _manifests:
        return _manifests

    for module_path, fallback in BUILTIN_SKILLS:
        registry._current_skill = fallback.id
        try:
            module = __import__(module_path, fromlist=["*"])
            manifest = getattr(module, "SKILL", None) or fallback
            _manifests[manifest.id] = manifest
            # A module may have been imported before the loader ran (lazy
            # imports elsewhere) — its tools were stamped None. Re-stamp by
            # the handler's defining module so the catalog stays accurate.
            for entry in registry._REGISTRY.values():
                if entry.get("skill") is None and \
                        getattr(entry["handler"], "__module__", "") == module_path:
                    entry["skill"] = manifest.id
        except Exception as e:
            print(f"  [skills] '{module_path}' unavailable: {e}")
        finally:
            registry._current_skill = None

    # Custom tools Freya wrote for herself (each file = one custom skill entry).
    registry._current_skill = "custom"
    try:
        from core.self_extend import load_custom_tools
        load_custom_tools()
        custom_dir = os.path.join(os.path.dirname(__file__), "custom")
        count = len([f for f in os.listdir(custom_dir)
                     if f.endswith(".py") and f != "__init__.py"])
        if count:
            _manifests["custom"] = SkillManifest(
                "custom", "Custom Tools", f"{count} self-written tool(s) in core/skills/custom")
    except Exception:
        pass
    finally:
        registry._current_skill = None

    return _manifests


def catalog(config: dict) -> list[dict]:
    """Skill catalog for the dashboard: manifest + tools + gate state."""
    from core import registry

    load_all()
    tools_by_skill: dict[str, list[str]] = {}
    for name, entry in registry._REGISTRY.items():
        tools_by_skill.setdefault(entry.get("skill") or "core", []).append(name)

    out = []
    for manifest in _manifests.values():
        enabled = registry._gate_open(manifest.gate, config) if manifest.gate else True
        out.append({
            "id": manifest.id,
            "name": manifest.name,
            "description": manifest.description,
            "gate": manifest.gate,
            "enabled": enabled,
            "version": manifest.version,
            "tools": sorted(tools_by_skill.get(manifest.id, [])),
        })

    # Markdown SKILL.md packs (core/md_skills.py) list alongside Python skills.
    try:
        from core.md_skills import catalog_entries
        out.extend(catalog_entries(config))
    except Exception:
        pass

    # MCP servers appear as synthetic skills.
    try:
        from core.mcp_client import mcp_manager
        for decl in mcp_manager.get_declarations():
            server = decl.name.split("__")[1] if "__" in decl.name else "mcp"
            entry = next((s for s in out if s["id"] == f"mcp_{server}"), None)
            if entry is None:
                entry = {"id": f"mcp_{server}", "name": f"MCP: {server}",
                         "description": "Tools from a connected MCP server",
                         "gate": f"mcp_servers.{server}.enabled", "enabled": True,
                         "version": "-", "tools": []}
                out.append(entry)
            entry["tools"].append(decl.name)
    except Exception:
        pass

    return sorted(out, key=lambda s: s["name"])
