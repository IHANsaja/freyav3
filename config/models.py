"""Gemini role defaults, checked against Google's model catalog 2026-09-16."""
TEXT_MODEL = "gemini-3.5-flash"
LITE_MODEL = "gemini-3.5-flash-lite"
LIVE_MODEL = "gemini-3.8-live"
LIVE_FALLBACK_MODEL = "gemini-3.1-flash-live-preview"
THINKING_LIVE_MODEL = "gemini-3.8-live-extended-thinking"

# Only aliases and retired models are migrated; supported explicit pins survive.
REPLACEMENTS = {
    "gemini-flash-latest": TEXT_MODEL,
    "gemini-flash-lite-latest": LITE_MODEL,
    "gemini-2.0-flash": TEXT_MODEL,
    "gemini-2.0-flash-001": TEXT_MODEL,
    "gemini-2.0-flash-lite": LITE_MODEL,
    "gemini-2.0-flash-lite-001": LITE_MODEL,
    "gemini-2.5-flash-preview-05-20": TEXT_MODEL,
    "gemini-2.5-flash-preview-09-25": TEXT_MODEL,
    "gemini-2.5-flash-lite-preview-09-2025": LITE_MODEL,
    "gemini-3.1-flash-lite-preview": LITE_MODEL,
    "gemini-3-pro-preview": "gemini-3.1-pro-preview",
    "gemini-2.0-flash-live-001": LIVE_MODEL,
    "gemini-live-2.5-flash-preview": LIVE_MODEL,
    "gemini-3.1-flash-image-preview": "gemini-3.1-flash-image",
    "gemini-3-pro-image-preview": "gemini-3-pro-image",
}


def normalize_models(value):
    """Normalize model fields only, never prompts or unrelated string values."""
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key in ("model", "id", "model_override") or key.endswith("_model")):
                prefix = "models/" if item.startswith("models/") else ""
                value[key] = prefix + REPLACEMENTS.get(item.removeprefix("models/"), item.removeprefix("models/"))
            elif isinstance(item, (dict, list)):
                normalize_models(item)
    elif isinstance(value, list):
        for item in value:
            normalize_models(item)
    return value


LIVE_MODELS = [
    {"id": LIVE_MODEL, "label": "Gemini 3.8 Live (main)"},
    {"id": THINKING_LIVE_MODEL, "label": "Gemini 3.8 Live Extended Thinking"},
    {"id": LIVE_FALLBACK_MODEL, "label": "Gemini 3.1 Flash Live (fallback)"},
]
COMPLEX_MODE = {
    "label": "Complex Tasks",
    "model_override": THINKING_LIVE_MODEL,
    "thinking_level": "high",
    "personality_override": "Work through this complex task carefully, verify important conclusions with tools, and give short progress updates. Keep the user's goal and constraints. Do not repeat completed actions.",
    "theme": {"accent": "#8b7cff", "glow": 0.8},
}


def migrate_live_defaults(config):
    """One-time upgrade; later explicit model choices and unrelated config survive."""
    from copy import deepcopy
    live = config.setdefault("live", {})
    if live.get("defaults_version", 0) >= 1:
        return False
    if config.get("active_model", LIVE_FALLBACK_MODEL).removeprefix("models/") in (
        LIVE_FALLBACK_MODEL, "gemini-2.0-flash-live-001", "gemini-live-2.5-flash-preview"
    ):
        config["active_model"] = LIVE_MODEL
    live.update(defaults_version=1)
    live.setdefault("fallback_model", LIVE_FALLBACK_MODEL)
    live.setdefault("auto_complex_mode", True)
    live.setdefault("thinking_level", "high")
    config.setdefault("modes", {}).setdefault("complex_tasks", deepcopy(COMPLEX_MODE))
    provider = config.setdefault("providers", {}).setdefault("gemini", {})
    old = provider.get("models", [])
    ids = {m["id"] for m in LIVE_MODELS}
    provider["models"] = deepcopy(LIVE_MODELS) + [m for m in old if m.get("id") not in ids]
    return True
