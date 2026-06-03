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

def get_active_voice(config):
    provider = config["active_provider"]
    return config["providers"][provider]["active_voice"]

def get_personality(config):
    return config["freya"]["personality"]

def get_app_path(config, app_name):
    return config["apps"].get(app_name, "")