import json
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "freya_config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
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
                            "personality_override": personality
                        }
                except Exception as le:
                    print(f"Error loading custom mode from {filename}: {le}")
    except Exception as e:
        print(f"Error listing config directory: {e}")
        
    return config

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
    if not override:
        return base_personality
    label = mode.get("label", mode_id)
    return (
        f"{base_personality}\n\n"
        f"[ACTIVE MODE \u2014 {label}]\n"
        f"{override}\n"
        "All of your tools and screen-control abilities remain fully available in this mode."
    )

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