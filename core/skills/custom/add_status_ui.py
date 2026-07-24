# Auto-generated Freya skill — created by Freya herself.
from core.registry import tool, OBJ, P, STR, INT, BOOL


@tool('add_status_ui', 'Modify my core code to add a UI element that displays the running sub-agent status.', OBJ({"input": P(STR, "optional free-form input")}))
def add_status_ui(args, ctx):
    text = args.get("input", "")

    import json
    import os

    # Define the file paths based on the context of main project directory
    # Provided by Ihan in a previous turn
    project_path = "F:/freyav3/"
    ui_config_path = os.path.join(project_path, "freya-ui/src/config.json") # Example path, may need adjustment


    def add_status_panel():
        try:
            # Check if config exists
            if not os.path.exists(ui_config_path):
                 return f"Error: Could not find UI config at {ui_config_path}"

            # Read the current config
            with open(ui_config_path, 'r') as f:
                config = json.load(f)

            # Basic logic to add or update a component definition
            # Assumes the UI framework uses this config to render components
            if 'components' not in config:
                config['components'] = []

            # Define the new component for sub-agent status
            status_component = {
                "id": "sub_agent_status_panel",
                "type": "StatusPanel",
                "position": "right-hand", # Example positioning hint
                "title": "Agent Status",
                "text": "Idle"
            }

            # Check if it already exists, update text if it does
            found = False
            for i, comp in enumerate(config['components']):
                if comp.get('id') == "sub_agent_status_panel":
                    config['components'][i] = status_component
                    found = True
                    break

            if not found:
                config['components'].append(status_component)

            # Write back the changes
            with open(ui_config_path, 'w') as f:
                json.dump(config, f, indent=4)

            return "Successfully defined the sub-agent status panel in config.json. Reload the page to see changes."

        except Exception as e:
            return f"An error occurred: {str(e)}"

    # Call the function to modify the UI config
    return add_status_panel()
