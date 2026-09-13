import json
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "freya_config.json")
EXAMPLE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "freya_config.example.json")


def ensure_config():
    """Create freya_config.json from the shipped example on first run.

    The real config is gitignored: it accumulates absolute paths to whatever is
    installed on the machine, which is personal to that machine and has no place
    in a public repository. Only the example is tracked, so a fresh clone starts
    from a clean template and diverges locally from there.
    """
    if os.path.exists(CONFIG_PATH):
        return
    if not os.path.exists(EXAMPLE_CONFIG_PATH):
        raise FileNotFoundError(
            f"Neither {CONFIG_PATH} nor {EXAMPLE_CONFIG_PATH} exists — the install is incomplete."
        )
    import shutil
    shutil.copyfile(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
    print("  Created config/freya_config.json from the example template.")


def load_config():
    ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    # New simulation-only capability defaults without rewriting existing installs.
    config.setdefault("trading", {"enabled": True})
    
    if "modes" not in config:
        config["modes"] = {}
        
    config_dir = os.path.dirname(CONFIG_PATH)
    try:
        for filename in os.listdir(config_dir):
            if filename.startswith("freya_") and filename.endswith(".json") and filename != "freya_config.json":
                mode_id = filename[6:-5]  # strip "freya_" prefix and ".json" suffix
                file_path = os.path.join(config_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as lf:
                        local_data = json.load(lf)
                    
                    personality = local_data.get("freya", {}).get("personality")
                    if personality:
                        config["modes"][mode_id] = {
                            "label": mode_id.replace("_", " ").title() + " Mode",
                            "model_override": local_data.get("active_model"),
                            "personality_override": personality,
                            # Optional persona extras a custom mode file may define
                            "voice_override": local_data.get("voice_override"),
                            "speech_style": local_data.get("speech_style"),
                            "theme": local_data.get("theme"),
                            "avatar_idle": local_data.get("avatar_idle"),
                        }
                except Exception as le:
                    print(f"Error loading custom mode from {filename}: {le}")
    except Exception as e:
        print(f"Error listing config directory: {e}")
        
    from config.models import LIVE_MODEL, TEXT_MODEL, normalize_models
    config.setdefault("active_provider", "gemini")
    config.setdefault("active_model", LIVE_MODEL)
    config["trading"].setdefault("gemini_model", TEXT_MODEL)
    return normalize_models(config)

def get_api_key():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY not found in .env file!")
    return key

def get_active_model(config):
    return config["active_model"]

def get_active_mode(config):
    return config.get("active_mode", "default")

def get_mode_personality(config, base_personality):
    """Combine the base personality with the mode's personality addendum.

    The base prompt carries Freya's tool and screen-control instructions.
    Previously the mode override REPLACED it entirely, which silently
    stripped all tool knowledge in non-default modes and caused Freya to
    hallucinate (e.g. describing an imaginary screen instead of calling
    capture_screen).
    """
    mode_id = get_active_mode(config)
    modes = config.get("modes", {})
    mode = modes.get(mode_id, {})
    override = mode.get("personality_override")
    style = mode.get("speech_style")
    if not override and not style:
        return base_personality
    label = mode.get("label", mode_id)
    parts = [base_personality]
    if override:
        parts.append(
            f"[ACTIVE MODE \u2014 {label}]\n{override}\n"
            "All of your tools and screen-control abilities remain fully available in this mode."
        )
    if style:
        parts.append(f"[DELIVERY] {style}")
    return "\n\n".join(parts)

def get_mode_model(config):
    """Returns mode-specific model override if set, otherwise returns active_model."""
    mode_id = get_active_mode(config)
    modes = config.get("modes", {})
    mode = modes.get(mode_id, {})
    override = mode.get("model_override")
    return override if override else config["active_model"]

def get_active_voice(config):
    provider = config["active_provider"]
    return config["providers"][provider]["active_voice"]

def get_mode_voice(config):
    """Mode-specific voice override, else the provider's active voice."""
    mode = config.get("modes", {}).get(get_active_mode(config), {})
    return mode.get("voice_override") or get_active_voice(config)

def get_mode_theme(config):
    """Mode UI theme: accent color, glow level, optional shader params, idle pose."""
    mode = config.get("modes", {}).get(get_active_mode(config), {})
    theme = mode.get("theme") or {}
    return {
        "accent": theme.get("accent", "#d32f2f"),
        "glow": float(theme.get("glow", 1.0)),
        "coreParams": theme.get("coreParams"),
        "avatarIdle": mode.get("avatar_idle", "standing"),
    }

def get_personality(config):
    return config["freya"]["personality"]

def get_app_path(config, app_name):
    return config["apps"].get(app_name, "")

def get_memory_api_key():
    """Get a separate API key for memory updates (falls back to main key)."""
    key = os.getenv("GEMINI_MEMORY_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("No API key found for memory updates!")
    return key


def get_agent_api_key():
    """Key for the call-heavy text agents — the browser, sub-agents, ambient, RAG.

    Prefers GEMINI_AGENT_API_KEY, then GEMINI_MEMORY_API_KEY, then the main key. Using a
    secondary key keeps these from eating the live-voice key's quota, and if it belongs to a
    different Google project it taps a separate free-tier quota."""
    key = (os.getenv("GEMINI_AGENT_API_KEY") or os.getenv("GEMINI_MEMORY_API_KEY")
           or os.getenv("GEMINI_API_KEY"))
    if not key:
        raise ValueError("No API key found for agents!")
    return key
