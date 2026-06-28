# Auto-generated Freya skill — created by Freya herself.
from core.registry import tool, OBJ, P, STR, INT, BOOL


@tool('toggle_listening', 'Toggles active listening mode. When turned off, I will stop processing user speech until it is turned back on. Use when Ihan wants to watch media without me responding.', OBJ({"input": P(STR, "optional free-form input")}))
def toggle_listening(args, ctx):
    text = args.get("input", "")
    import json
    import os

    # Define config path - assuming relative to the run directory
    CONFIG_PATH = 'config.json'

    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {}

    # Get current state, default to True (listening)
    current_state = config.get('active_listening', True)
    new_state = not current_state

    # Update config dictionary
    config['active_listening'] = new_state

    # Write updated config back to disk
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)

    state_desc = "disabled" if not new_state else "enabled"
    return f"Active listening has been {state_desc}."
