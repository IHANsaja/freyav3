"""The user's personality choices for Freya, made in the dashboard customizer.

Stored under config["persona"]. A style picks the live model and a sensible
starting point for the sliders; the sliders and the user's own note become a
short block appended to the base personality, so the base prompt (tools,
screen control, safety) is never replaced - only tuned.
"""
import os
import re

from config.models import LIVE_FALLBACK_MODEL, LIVE_MODEL, THINKING_LIVE_MODEL

STYLES = {
    "friendly": {
        "label": "Friendly",
        "model": LIVE_FALLBACK_MODEL,
        "model_label": "Gemini 3.1 Flash Live",
        "summary": "Her most friendly and energetic version - warm, chatty and playful.",
        "traits": {"warmth": 90, "humor": 75, "detail": 50, "initiative": 60},
        "prompt": "Lead with warmth and energy. Enjoy the conversation, react to how he feels, "
                  "and keep things lively while you help.",
    },
    "quick": {
        "label": "Quick",
        "model": LIVE_MODEL,
        "model_label": "Gemini 3.8 Live",
        "summary": "Faster responses and quick work - efficient, a little less chatty.",
        "traits": {"warmth": 55, "humor": 35, "detail": 25, "initiative": 55},
        "prompt": "Favour speed. Answer in as few words as it takes, act straight away, and "
                  "skip small talk unless he starts it.",
    },
    "focused": {
        "label": "Focused",
        "model": THINKING_LIVE_MODEL,
        "model_label": "Gemini 3.8 Live Extended Thinking",
        "summary": "Puts the task before conversation - best for harder, multi-step work.",
        "traits": {"warmth": 35, "humor": 15, "detail": 75, "initiative": 80},
        "prompt": "Put the task first. Think it through, verify results with tools, and report "
                  "progress plainly. Keep conversation brief and on topic.",
    },
}
DEFAULT_STYLE = "quick"

# Each slider maps to three bands of instruction: low (<34), middle, high (>66).
TRAITS = {
    "warmth": ("Warmth",
               "Keep a calm, matter-of-fact tone; stay polite but reserved.",
               "Be friendly and easy-going.",
               "Be openly warm and caring; celebrate his wins and encourage him when things go wrong."),
    "humor": ("Humour",
              "Stay serious; no jokes or teasing.",
              "Allow a light touch of humour when it fits.",
              "Be playful: tease gently, joke often, keep it fun."),
    "detail": ("Detail",
               "Keep spoken answers to a sentence or two.",
               "Give answers of moderate length, with detail only when it helps.",
               "Explain thoroughly: give reasons, steps and context."),
    "initiative": ("Initiative",
                   "Do exactly what he asks and check before anything extra.",
                   "Suggest a next step when it is clearly useful.",
                   "Be proactive: anticipate the next step, offer ideas and handle follow-ups without being asked."),
}

ACCENTS = ["#0f9c6e", "#22b8cf", "#8b7cff", "#e0559a", "#f2994a", "#e8c547"]
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_NOTE_MAX = 400
_NAME_MAX = 40


def get_persona(config):
    """The saved persona with every field filled, for the customizer to edit."""
    saved = config.get("persona") or {}
    style = saved.get("style") if saved.get("style") in STYLES else DEFAULT_STYLE
    traits = dict(STYLES[style]["traits"])
    traits.update({k: v for k, v in (saved.get("traits") or {}).items() if k in TRAITS})
    return {
        "setup_done": bool(saved.get("setup_done")),
        "style": style,
        "traits": traits,
        "accent": saved.get("accent") or ACCENTS[0],
        "note": saved.get("note", ""),
    }


def validate(body):
    """Clean a customizer submission. Raises ValueError with a user-facing message."""
    style = body.get("style", DEFAULT_STYLE)
    if style not in STYLES:
        raise ValueError(f"Unknown style {style!r}. Choose one of: {', '.join(STYLES)}.")
    traits = {}
    for key, value in (body.get("traits") or {}).items():
        if key not in TRAITS:
            raise ValueError(f"Unknown trait {key!r}.")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError(f"{key} must be a number from 0 to 100.")
        traits[key] = int(value)
    accent = body.get("accent") or ACCENTS[0]
    if not isinstance(accent, str) or not _HEX.match(accent):
        raise ValueError("accent must be a colour like #0f9c6e.")
    note = str(body.get("note") or "").strip()
    if len(note) > _NOTE_MAX:
        raise ValueError(f"The note can be at most {_NOTE_MAX} characters.")
    name = str(body.get("name") or "").strip()
    if len(name) > _NAME_MAX or any(c in name for c in "\r\n#"):
        raise ValueError(f"The name must be one line of at most {_NAME_MAX} characters.")
    return {"style": style, "traits": traits, "accent": accent, "note": note}, name


def _band(value):
    return 0 if value < 34 else (2 if value > 66 else 1)


def prompt_block(config):
    """Personality tuning appended to the base prompt; '' until the user has chosen."""
    saved = config.get("persona") or {}
    if not saved.get("setup_done"):
        return ""
    persona = get_persona(config)
    lines = [STYLES[persona["style"]]["prompt"]]
    lines += [TRAITS[k][1 + _band(v)] for k, v in persona["traits"].items()]
    if persona["note"]:
        lines.append(f"He also asked for this: {persona['note']}")
    return ("[PERSONALITY TUNING - chosen by the user; where it differs from the tone "
            "described above, this wins]\n" + "\n".join(f"- {line}" for line in lines))


def catalog():
    """Static choices the customizer renders."""
    return {
        "styles": {k: {f: v[f] for f in ("label", "model", "model_label", "summary", "traits")}
                   for k, v in STYLES.items()},
        "trait_info": {k: {"label": v[0], "low": v[1], "mid": v[2], "high": v[3]} for k, v in TRAITS.items()},
        "accents": ACCENTS,
    }


def save_preferred_name(name):
    """Record what Freya should call the user in memory/MEMORY.md - the one
    place core/user_identity.py reads a name from. Updates an existing
    'Preferred name:' line, or adds one without touching anything else."""
    from core.user_identity import MEMORY_MD_PATHS, memory_md_path
    if not name:
        return
    path = memory_md_path() or MEMORY_MD_PATHS[0]
    line = f"- Preferred name: {name}"
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = f"# Freya Memory - {name}\n\n## Personal\n- Name: {name}\n{line}\n"
    else:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
        pattern = re.compile(r"^\s*[-*]?\s*preferred\s*name\s*[:=].*$", re.IGNORECASE | re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub(lambda _: line, text, count=1)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
