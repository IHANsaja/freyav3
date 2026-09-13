"""Gemini role defaults, checked against Google's model catalog 2026-09-13."""
TEXT_MODEL = "gemini-3.5-flash"
LITE_MODEL = "gemini-3.5-flash-lite"
LIVE_MODEL = "gemini-3.1-flash-live-preview"

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
