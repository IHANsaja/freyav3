"""
career-ops bridge — Freya drives the santifer/career-ops job-search system by voice.

career-ops (github.com/santifer/career-ops) is a Node/Playwright system whose
capabilities live as markdown "modes" (modes/*.md) written for an AI coding CLI:
scan job portals, evaluate a posting against an A-G rubric, tailor a CV, generate
PDFs, track applications. It's built on the same agent-skill idea as
core/md_skills.py, so rather than reimplement any of it we bridge to the real
checkout and let it stay updatable via its own `npm run update`.

Two impedance mismatches this module resolves:

  • **Format.** career-ops modes have no YAML frontmatter — they open with
    `# Mode: <id> — <Title>` followed by a description paragraph. `_parse_mode`
    reads that shape, so md_skills' frontmatter parser isn't forced to guess.
  • **Runtime.** career-ops expects an interactive coding CLI with file/bash
    access. Freya is a voice session, so the split is: her *own* tools do the
    agent work the mode describes (web_search, browser_task, read/write file),
    while the deterministic zero-token Node scripts run through
    `run_career_script`.

Nothing here submits an application, sends an email, or spends money —
career-ops is explicitly human-in-the-loop by design, and that property is
preserved: Freya reports and drafts, Ihan decides.
"""

import os
import re
import subprocess

from core.registry import tool, OBJ, P, STR, ARR

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# `npx career-ops init` clones into ./career-ops/career-ops (a dir inside the dir).
_CANDIDATES = [
    os.path.join(_PROJECT_ROOT, "career-ops", "career-ops"),
    os.path.join(_PROJECT_ROOT, "career-ops"),
]

MAX_BODY = 20_000
SCRIPT_TIMEOUT = 900
MAX_OUT = 16_000

_HEADING = re.compile(r"^#\s*Mode:\s*(?P<id>[\w.-]+)\s*[—–-]\s*(?P<title>.+?)\s*$", re.M)

# The modes worth surfacing by voice. career-ops ships 34 including templates,
# translations and deep-internals; listing all of them in a tool description
# would drown the model in options it can't meaningfully choose between.
_VOICE_MODES = {
    "scan": "Scan configured job portals and add newly-found openings to the pipeline",
    "oferta": "Evaluate one job posting (paste text or a URL) against the full A-G rubric",
    "ofertas": "Evaluate several job postings in one batch",
    "pipeline": "Show the current pipeline — what's been found, evaluated and applied to",
    "tracker": "Read and update the application tracker",
    "cover": "Draft a tailored cover letter for a specific role",
    "pdf": "Generate a tailored ATS-friendly CV PDF for a role",
    "interview-prep": "Prepare for an interview at a specific company",
    "followup": "Work out which applications are due a follow-up",
    "titles": "Suggest job titles worth searching for, based on the CV",
    "upskill": "Identify skill gaps against target roles",
}


def install_root() -> str | None:
    for path in _CANDIDATES:
        if os.path.isdir(os.path.join(path, "modes")):
            return path
    return None


def _parse_mode(md_path: str) -> tuple[str, str]:
    """→ (title, description) from a career-ops mode file."""
    try:
        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except Exception:
        return "", ""
    m = _HEADING.search(head)
    title = m.group("title").strip() if m else os.path.basename(md_path)[:-3]
    body = head[m.end():] if m else head
    desc = ""
    for para in body.split("\n\n"):
        clean = " ".join(para.split())
        if clean and not clean.startswith((">", "#", "-", "*", "|")):
            desc = clean
            break
    return title, desc[:300]


def discover_modes() -> dict[str, dict]:
    root = install_root()
    if root is None:
        return {}
    modes_dir = os.path.join(root, "modes")
    out: dict[str, dict] = {}
    for fn in sorted(os.listdir(modes_dir)):
        if not fn.endswith(".md") or fn.startswith("_") or fn == "README.md":
            continue
        mid = fn[:-3]
        path = os.path.join(modes_dir, fn)
        title, desc = _parse_mode(path)
        out[mid] = {
            "id": mid,
            "title": title,
            "description": _VOICE_MODES.get(mid) or desc,
            "path": path,
            "featured": mid in _VOICE_MODES,
        }
    return out


def _ready() -> tuple[bool, str]:
    root = install_root()
    if root is None:
        return False, ("career-ops isn't installed. Run "
                       "'npx @santifer/career-ops init' inside the Freya project's "
                       "career-ops folder.")
    if not os.path.isfile(os.path.join(root, "cv.md")):
        return False, "career-ops is installed but there's no cv.md yet, so it can't evaluate fit."
    return True, root


def _build_decl() -> str:
    base = (
        "Load one career-ops job-search workflow and follow it. career-ops is Ihan's job "
        "search system: it finds openings, scores them against a structured A-G rubric, "
        "tailors his CV, drafts cover letters and tracks applications. Call this BEFORE "
        "doing any job-search work so you follow the real procedure instead of improvising. "
        "It never applies or sends anything on its own — you evaluate and draft, Ihan decides. "
    )
    modes = discover_modes()
    if not modes:
        return base + "(career-ops is not installed yet.)"
    lines = [f"- {m['id']}: {m['description']}" for m in modes.values() if m["featured"]]
    extra = sorted(m["id"] for m in modes.values() if not m["featured"])
    text = base + "Workflows:\n" + "\n".join(lines)
    if extra:
        text += "\nAlso available: " + ", ".join(extra) + "."
    return text


@tool(
    "use_career_mode",
    _build_decl(),
    OBJ({"mode": P(STR, "The workflow id, e.g. scan, oferta, pipeline")}, ["mode"]),
)
def use_career_mode(args, ctx) -> str:
    ok, root = _ready()
    if not ok:
        return root
    mode = (args.get("mode") or "").strip().lower()
    modes = discover_modes()
    entry = modes.get(mode)
    if entry is None:
        aliases = {"job": "oferta", "jobs": "ofertas", "evaluate": "oferta",
                   "search": "scan", "status": "pipeline", "cv": "pdf",
                   "resume": "pdf", "letter": "cover", "interview": "interview-prep"}
        entry = modes.get(aliases.get(mode, ""))
    if entry is None:
        featured = ", ".join(m["id"] for m in modes.values() if m["featured"])
        return f"career-ops has no '{mode}' workflow. The main ones are: {featured}."

    try:
        with open(entry["path"], "r", encoding="utf-8", errors="replace") as f:
            body = f.read()
    except Exception as e:
        return f"Couldn't read that workflow: {e}"
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n…(truncated)"

    return (
        f"[CAREER-OPS WORKFLOW — {entry['id']}: {entry['title']}]\n"
        f"Working directory: {root}\n"
        f"Ihan's CV is {os.path.join(root, 'cv.md')} and his profile is "
        f"{os.path.join(root, 'config', 'profile.yml')}.\n"
        "Follow the procedure below. Where it tells you to browse or search, use your own "
        "web_search / web_fetch / browser_task tools; where it names a Node script, run it "
        "with run_career_script. Deliver the result out loud, conversationally — lead with "
        "the verdict and the score, then the reasoning. Never apply, submit or send "
        "anything; draft it and let Ihan decide.\n\n"
        f"{body}"
    )


@tool(
    "run_career_script",
    "Run one of career-ops' built-in Node scripts — the deterministic parts of the job "
    "pipeline (portal scanning, tracker checks, PDF generation). Use only when a career-ops "
    "workflow told you to. Common commands: 'scan' (find new openings), 'verify' (check "
    "pipeline integrity), 'pipeline' (status), 'dedup', 'normalize', 'doctor' (diagnose setup).",
    OBJ({"command": P(STR, "npm script name, e.g. scan, verify, doctor, pdf"),
         "args": P(ARR, "Extra command-line arguments", items=P(STR))},
        ["command"]),
    dangerous=True,
)
def run_career_script(args, ctx) -> str:
    ok, root = _ready()
    if not ok:
        return root
    command = (args.get("command") or "").strip()
    if not re.fullmatch(r"[\w:.-]+", command):
        return "That doesn't look like a valid career-ops command."

    cmd = ["npm", "--prefix", root, "run", command]
    extra = [str(a) for a in (args.get("args") or [])]
    if extra:
        cmd += ["--"] + extra
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=SCRIPT_TIMEOUT, cwd=root, shell=(os.name == "nt"))
    except subprocess.TimeoutExpired:
        return f"The {command} job was still running after 15 minutes, so I stopped it."
    except FileNotFoundError:
        return "I couldn't find Node/npm on this machine, so I can't run career-ops scripts."
    except Exception as e:
        return f"Couldn't run {command}: {e}"

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + "\n…(truncated)"
    if proc.returncode != 0:
        detail = err[:1500] or out[:1500]
        if "Missing script" in detail:
            return f"career-ops has no '{command}' script."
        return f"The {command} job failed.\n{detail}"
    return out or "That finished with nothing to report."


@tool(
    "career_status",
    "Check whether Ihan's job-search system is set up and what's in his pipeline right now.",
    OBJ(),
)
def career_status(args, ctx) -> str:
    root = install_root()
    if root is None:
        return "career-ops isn't installed yet."
    bits = [f"career-ops is installed at {root}"]
    bits.append("CV is in place" if os.path.isfile(os.path.join(root, "cv.md"))
                else "there's no cv.md yet")
    profile = os.path.join(root, "config", "profile.yml")
    if os.path.isfile(profile):
        try:
            with open(profile, "r", encoding="utf-8") as f:
                todos = sum(1 for line in f if "TODO" in line)
            bits.append(f"profile is configured{f' but has {todos} field(s) still to fill in' if todos else ''}")
        except Exception:
            bits.append("profile is present")
    else:
        bits.append("no profile.yml yet")

    tracker = os.path.join(root, "data", "tracker.md")
    if os.path.isfile(tracker):
        try:
            with open(tracker, "r", encoding="utf-8", errors="replace") as f:
                rows = [l for l in f if l.strip().startswith("|")]
            bits.append(f"the tracker holds roughly {max(0, len(rows) - 2)} application(s)")
        except Exception:
            pass
    else:
        bits.append("nothing tracked yet")
    return "; ".join(bits) + "."
