"""
Markdown skills — Claude-style SKILL.md capability packs, with progressive disclosure.

This is a *second*, complementary skill system alongside core/skills/loader.py.
The loader handles **Python** skills (modules that register callable tools via
`@tool`). This module handles **markdown** skills: a folder containing a
`SKILL.md` whose YAML frontmatter names it and whose body is a set of
instructions Freya follows. That's the same shape the wider agent-skill
ecosystem uses (Claude Code plugins, `npx skills add`, the Agent Skill
Standard), so third-party skills can be dropped in essentially unmodified.

    skills/
      watch/
        SKILL.md          ← frontmatter: name, description; body: instructions
        scripts/
          watch.py        ← optional bundled executables

Progressive disclosure — the whole point
----------------------------------------
Loading every skill's full instructions into a live voice model's context would
be enormously wasteful and would crowd out the conversation. Instead, exactly
like Claude:

  1. Every skill's **name + description only** is always visible — baked into
     the `use_skill` tool declaration at import time (see `_build_decl`), so
     Gemini can see what exists and decide when something is relevant.
  2. The **full body** is loaded only when Freya actually calls
     `use_skill(name)` — at which point the instructions enter the conversation
     and she follows them.
  3. Bundled **scripts** are executed on demand via `run_skill_script`, so a
     skill can carry real code without that code ever occupying context.

Skills are discovered from `skills/` at the project root (and any extra paths in
config `skills.paths`), so users can add capabilities without touching Python.
"""

import os
import subprocess
import sys

from core.registry import tool, OBJ, P, STR, ARR

SKILLS_DIRNAME = "skills"
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKILLS_DIR = os.path.join(_PROJECT_ROOT, SKILLS_DIRNAME)

MAX_BODY = 24_000      # chars of SKILL.md body handed to the model
SCRIPT_TIMEOUT = 900   # seconds — video/transcode work is genuinely slow
MAX_SCRIPT_OUT = 20_000


# ══════════════════════════════════════════════
#  DISCOVERY
# ══════════════════════════════════════════════
def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body).

    Frontmatter is the standard leading `---` fenced YAML block. A file without
    one is still a valid skill — it just has no metadata, and the folder name
    becomes its id.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw, body = parts[1], parts[2]
    try:
        import yaml
        meta = yaml.safe_load(raw) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        # Minimal fallback so a malformed/unavailable YAML parser doesn't hide
        # the skill entirely — pull simple `key: value` lines.
        meta = {}
        for line in raw.splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip("'\"")
    return meta, body.lstrip("\n")


def _skill_dirs(config: dict | None = None) -> list[str]:
    dirs = [_SKILLS_DIR]
    for extra in ((config or {}).get("skills", {}) or {}).get("paths", []) or []:
        dirs.append(os.path.abspath(os.path.expanduser(extra)))
    return dirs


def discover(config: dict | None = None) -> dict[str, dict]:
    """Find every markdown skill. Returns {id: {...metadata, path, md_path}}.

    Deliberately re-scans on each call rather than caching: dropping a new
    skill folder in should take effect on the next session with no restart
    dance, and this is only ever called a handful of times per session.
    """
    found: dict[str, dict] = {}
    for root in _skill_dirs(config):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            skill_dir = os.path.join(root, entry)
            md_path = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isfile(md_path):
                continue
            try:
                with open(md_path, "r", encoding="utf-8", errors="replace") as f:
                    meta, _body = _parse_frontmatter(f.read())
            except Exception:
                continue
            sid = str(meta.get("name") or entry).strip()
            found[sid] = {
                "id": sid,
                "name": sid,
                "description": str(meta.get("description") or "").strip(),
                "version": str(meta.get("version") or "1.0"),
                "path": skill_dir,
                "md_path": md_path,
            }
    return found


def catalog_entries(config: dict | None = None) -> list[dict]:
    """Markdown skills rendered for the dashboard's skill catalog."""
    out = []
    for s in discover(config).values():
        scripts_dir = os.path.join(s["path"], "scripts")
        scripts = []
        if os.path.isdir(scripts_dir):
            scripts = sorted(f for f in os.listdir(scripts_dir)
                             if not f.startswith("_") and f.endswith((".py", ".sh", ".ps1")))
        out.append({
            "id": f"md_{s['id']}",
            "name": s["name"],
            "description": s["description"] or "Markdown skill",
            "gate": None,
            "enabled": True,
            "version": s["version"],
            "kind": "markdown",
            "tools": scripts,
        })
    return out


# ══════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════
def _build_decl() -> str:
    """Tool description listing every installed skill — this is what makes
    names+descriptions permanently visible without their bodies."""
    skills = discover()
    base = (
        "Load the full instructions for one of your installed skills, then follow them. "
        "A skill is a capability pack that teaches you how to do something specific — you "
        "only see its summary until you call this, so call it BEFORE attempting any task a "
        "skill covers. "
    )
    if not skills:
        return base + "(No skills are installed yet — they live in the project's skills/ folder.)"
    lines = [f"- {s['id']}: {s['description'] or 'no description'}" for s in skills.values()]
    return base + "Installed skills:\n" + "\n".join(lines)


@tool(
    "use_skill",
    _build_decl(),
    OBJ({"name": P(STR, "The skill id to load, exactly as listed")}, ["name"]),
)
def use_skill(args, ctx) -> str:
    name = (args.get("name") or "").strip()
    skills = discover(getattr(ctx, "config", None))
    if not skills:
        return "I don't have any skills installed yet."
    skill = skills.get(name)
    if skill is None:  # tolerate case/spacing drift from a voice transcript
        norm = name.lower().replace(" ", "-").replace("_", "-")
        skill = next((s for k, s in skills.items()
                      if k.lower().replace(" ", "-").replace("_", "-") == norm), None)
    if skill is None:
        return f"I don't have a skill called '{name}'. I have: {', '.join(skills)}."
    try:
        with open(skill["md_path"], "r", encoding="utf-8", errors="replace") as f:
            _meta, body = _parse_frontmatter(f.read())
    except Exception as e:
        return f"Couldn't read that skill: {e}"
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n…(instructions truncated)"
    return (
        f"[SKILL LOADED — {skill['id']}]\n"
        f"Its folder is {skill['path']}; run any bundled script with run_skill_script.\n"
        f"Follow these instructions now:\n\n{body}"
    )


@tool(
    "list_skills",
    "List the skills you have installed, with what each one does.",
    OBJ(),
)
def list_skills(args, ctx) -> str:
    skills = discover(getattr(ctx, "config", None))
    if not skills:
        return "I don't have any markdown skills installed yet."
    lines = [f"{s['id']} — {s['description'] or 'no description'}" for s in skills.values()]
    return "My installed skills: " + "; ".join(lines)


@tool(
    "run_skill_script",
    "Run a script that ships inside one of your skills (from its scripts/ folder). Use this "
    "only after use_skill told you to — its instructions say which script to run and with "
    "what arguments. Long jobs like video processing are expected to take a while.",
    OBJ({"skill": P(STR, "The skill id that owns the script"),
         "script": P(STR, "Script filename, e.g. watch.py"),
         "args": P(ARR, "Command-line arguments to pass", items=P(STR))},
        ["skill", "script"]),
    dangerous=True,
)
def run_skill_script(args, ctx) -> str:
    skills = discover(getattr(ctx, "config", None))
    skill = skills.get((args.get("skill") or "").strip())
    if skill is None:
        return f"I don't have a skill called '{args.get('skill')}'."

    script = os.path.basename((args.get("script") or "").strip())  # no path escapes
    script_path = os.path.join(skill["path"], "scripts", script)
    if not os.path.isfile(script_path):
        return f"{skill['id']} has no script called {script}."

    if script.endswith(".py"):
        cmd = [sys.executable, script_path]
    elif script.endswith(".ps1"):
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path]
    else:
        cmd = [script_path]
    cmd += [str(a) for a in (args.get("args") or [])]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=SCRIPT_TIMEOUT, cwd=skill["path"])
    except subprocess.TimeoutExpired:
        return f"{script} was still running after {SCRIPT_TIMEOUT // 60} minutes, so I stopped it."
    except Exception as e:
        return f"Couldn't run {script}: {e}"

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if len(out) > MAX_SCRIPT_OUT:
        out = out[:MAX_SCRIPT_OUT] + "\n…(output truncated)"
    if proc.returncode != 0:
        return f"{script} failed (exit {proc.returncode}).\n{err[:2000] or out[:2000]}"
    return out or err[:2000] or f"{script} finished with nothing to report."
