import json
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "freya_config.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

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
    """Returns mode-specific personality if set, otherwise falls back to base."""
    mode_id = get_active_mode(config)
    modes = config.get("modes", {})
    mode = modes.get(mode_id, {})
    override = mode.get("personality_override")
    return override if override else base_personality

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