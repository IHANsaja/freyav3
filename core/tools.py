import subprocess
import webbrowser
import os
import time
import threading
import urllib.parse
import urllib.request
import json
from datetime import datetime


# ─────────────────────────────────────────────
#  PROCESS NAME MAP  (used by close_app)
# ─────────────────────────────────────────────
APP_PROCESS_MAP = {
    "valorant":    ["RiotClientServices.exe", "VALORANT.exe"],
    "photoshop":   ["Photoshop.exe"],
    "illustrator": ["Illustrator.exe"],
    "discord":     ["Discord.exe"],
    "telegram":    ["Telegram.exe"],
    "steam":       ["steam.exe"],
    "word":        ["WINWORD.EXE"],
    "powerpoint":  ["POWERPNT.EXE"],
    "outlook":     ["OUTLOOK.EXE"],
    "edge":        ["msedge.exe"],
    "vscode":      ["Code.exe"],
    "chrome":      ["chrome.exe"],
    "spotify":     ["Spotify.exe"],
}


# ══════════════════════════════════════════════
#  1. OPEN APP
# ══════════════════════════════════════════════
def open_app(name: str, config: dict) -> str:
    """Launch an application by name using path from config."""
    name = name.lower().strip()
    path = config.get("apps", {}).get(name, "")

    if not path:
        return f"I don't have a path configured for {name}. Please add it to freya_config.json."

    try:
        if name == "work":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen([path])
        return f"{name.capitalize()} is launching!"
    except Exception as e:
        return f"Failed to open {name}: {str(e)}"


# ══════════════════════════════════════════════
#  2. CLOSE APP
# ══════════════════════════════════════════════
def close_app(name: str) -> str:
    """Kill an application process by name."""
    name = name.lower().strip()
    processes = APP_PROCESS_MAP.get(name)

    if not processes:
        return f"I don't know the process name for {name}."

    try:
        for proc in processes:
            subprocess.Popen(
                f"TASKKILL /F /IM {proc}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        return f"{name.capitalize()} is closing."
    except Exception as e:
        return f"Failed to close {name}: {str(e)}"


# ══════════════════════════════════════════════
#  3. WEB SEARCH
# ══════════════════════════════════════════════
def web_search(query: str) -> str:
    """Open a Google search in the default browser."""
    encoded = urllib.parse.quote(query)
    url = f"https://www.google.com/search?q={encoded}"
    webbrowser.open(url)
    return f"Opening Google search for: {query}"


# ══════════════════════════════════════════════
#  4. PLAY YOUTUBE
# ══════════════════════════════════════════════
def play_youtube(query: str) -> str:
    """Search and open YouTube for a given query."""
    encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    webbrowser.open(url)
    return f"Opening YouTube for: {query}"


# ══════════════════════════════════════════════
#  5. GET NEWS
# ══════════════════════════════════════════════
def get_news(topic: str = "world") -> str:
    """Fetch top news headlines for a topic using GNews API (free, no key needed)."""
    try:
        encoded = urllib.parse.quote(topic)
        url = f"https://gnews.io/api/v4/search?q={encoded}&lang=en&max=3&apikey=demo"
        # Fallback: open Google News in browser
        news_url = f"https://news.google.com/search?q={encoded}&hl=en"
        webbrowser.open(news_url)
        return f"Opening Google News for: {topic}"
    except Exception as e:
        return f"Could not fetch news: {str(e)}"


# ══════════════════════════════════════════════
#  6. SHUTDOWN COMPUTER
# ══════════════════════════════════════════════
def shutdown_computer(delay_seconds: int = 30) -> str:
    """Shutdown the computer after a delay."""
    try:
        subprocess.Popen(f"shutdown /s /t {delay_seconds}", shell=True)
        return f"Computer will shut down in {delay_seconds} seconds."
    except Exception as e:
        return f"Shutdown failed: {str(e)}"


# ══════════════════════════════════════════════
#  7. TAKE SCREENSHOT
# ══════════════════════════════════════════════
def take_screenshot() -> str:
    """Take a screenshot and save it to the Desktop."""
    try:
        import pyautogui
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        path = os.path.join(desktop, f"freya_screenshot_{timestamp}.png")
        screenshot = pyautogui.screenshot()
        screenshot.save(path)
        return f"Screenshot saved to your Desktop as freya_screenshot_{timestamp}.png"
    except ImportError:
        return "pyautogui is not installed. Run: pip install pyautogui"
    except Exception as e:
        return f"Screenshot failed: {str(e)}"


# ══════════════════════════════════════════════
#  8. OPEN FOLDER
# ══════════════════════════════════════════════
def open_folder(name: str, config: dict) -> str:
    """Open a configured folder in Windows Explorer."""
    name = name.lower().strip()
    path = config.get("apps", {}).get(name, "")

    if not path:
        return f"No folder path configured for {name}. Add it to freya_config.json under apps."

    try:
        subprocess.Popen(["explorer", path])
        return f"Opening {name} folder."
    except Exception as e:
        return f"Failed to open folder: {str(e)}"


# ══════════════════════════════════════════════
#  9. GET WEATHER
# ══════════════════════════════════════════════
def get_weather(city: str) -> str:
    """Get current weather for a city using wttr.in (free, no API key needed)."""
    try:
        encoded = urllib.parse.quote(city)
        url = f"https://wttr.in/{encoded}?format=3"
        req = urllib.request.Request(url, headers={"User-Agent": "FreyaAI/3.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode("utf-8").strip()
        return f"Weather in {result}"
    except Exception as e:
        return f"Could not fetch weather for {city}: {str(e)}"


# ══════════════════════════════════════════════
#  10. SET REMINDER
# ══════════════════════════════════════════════
def set_reminder(message: str, minutes: int) -> str:
    """Set a reminder that Freya will speak after X minutes."""
    def _remind():
        time.sleep(minutes * 60)
        # Windows toast notification as backup
        subprocess.Popen(
            f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
            f'[System.Windows.Forms.MessageBox]::Show(\'{message}\', \'Freya Reminder\')"',
            shell=True
        )

    thread = threading.Thread(target=_remind, daemon=True)
    thread.start()
    return f"Reminder set! I'll remind you in {minutes} minute{'s' if minutes != 1 else ''}: {message}"


# ══════════════════════════════════════════════
#  11. SEARCH DOCS
# ══════════════════════════════════════════════
def search_docs(technology: str, query: str) -> str:
    """Search official documentation for a technology."""
    doc_urls = {
        "python":     "https://docs.python.org/3/search.html?q=",
        "react":      "https://react.dev/search?q=",
        "javascript": "https://developer.mozilla.org/en-US/search?q=",
        "typescript": "https://www.typescriptlang.org/search?q=",
        "nodejs":     "https://nodejs.org/en/search/results?query=",
        "css":        "https://developer.mozilla.org/en-US/search?q=css+",
        "html":       "https://developer.mozilla.org/en-US/search?q=html+",
        "docker":     "https://docs.docker.com/search/?q=",
        "git":        "https://git-scm.com/search/results?search%5Bquery%5D=",
        "fastapi":    "https://fastapi.tiangolo.com/search?q=",
    }

    tech_lower = technology.lower().strip()
    encoded_query = urllib.parse.quote(query)

    base_url = doc_urls.get(tech_lower)
    if base_url:
        webbrowser.open(base_url + encoded_query)
        return f"Opening {technology} documentation for: {query}"
    else:
        # Fallback to Google search targeting docs
        fallback = f"https://www.google.com/search?q={urllib.parse.quote(technology + ' ' + query + ' documentation')}"
        webbrowser.open(fallback)
        return f"Searching documentation for {technology}: {query}"


# ══════════════════════════════════════════════
#  12. EXPLAIN ERROR
# ══════════════════════════════════════════════
def explain_error(error_text: str) -> str:
    """Search for an error message on Google and Stack Overflow."""
    encoded = urllib.parse.quote(error_text)
    # Open Stack Overflow search
    so_url = f"https://stackoverflow.com/search?q={encoded}"
    webbrowser.open(so_url)
    return f"I've opened Stack Overflow to help explain this error. Meanwhile, this looks like it could be related to: {error_text[:100]}"


# ══════════════════════════════════════════════
#  13. OPEN PROJECT
# ══════════════════════════════════════════════
def open_project(project_name: str, config: dict) -> str:
    """Open a project folder in VS Code."""
    projects = config.get("projects", {})
    path = projects.get(project_name.lower().strip(), "")

    if not path:
        return f"No project path configured for {project_name}. Add it to freya_config.json under projects."

    try:
        subprocess.Popen(["code", path], shell=True)
        return f"Opening {project_name} in VS Code."
    except Exception as e:
        return f"Failed to open project: {str(e)}"


# ══════════════════════════════════════════════
#  14. RUN TERMINAL COMMAND
# ══════════════════════════════════════════════
def run_terminal_command(command: str) -> str:
    """Run a shell command and return the output as text for Freya to speak."""
    # Safety: block dangerous commands
    blocked = ["rm ", "del ", "format ", "shutdown", "rmdir", ":(){", "mkfs"]
    for danger in blocked:
        if danger.lower() in command.lower():
            return f"I won't run that command for safety reasons: {command}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15
        )
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            return "Command ran successfully with no output."
        # Trim output so Freya doesn't read 500 lines
        lines = output.split("\n")
        if len(lines) > 10:
            summary = "\n".join(lines[:10])
            return f"Command output (first 10 lines): {summary} ... and {len(lines) - 10} more lines."
        return f"Command output: {output}"
    except subprocess.TimeoutExpired:
        return "Command timed out after 15 seconds."
    except Exception as e:
        return f"Command failed: {str(e)}"


# ══════════════════════════════════════════════
#  15. SEARCH STACKOVERFLOW
# ══════════════════════════════════════════════
def search_stackoverflow(query: str) -> str:
    """Search Stack Overflow and open the best result."""
    try:
        encoded = urllib.parse.quote(query)
        # Use Stack Exchange API (free, no key for basic search)
        api_url = f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q={encoded}&site=stackoverflow&pagesize=1&filter=withbody"
        req = urllib.request.Request(api_url, headers={"Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("items"):
            top = data["items"][0]
            title = top.get("title", "Unknown")
            link = top.get("link", "")
            is_answered = top.get("is_answered", False)
            score = top.get("score", 0)
            webbrowser.open(link)
            status = "answered" if is_answered else "unanswered"
            return f"Found a Stack Overflow result: {title}. It is {status} with a score of {score}. Opening it in your browser now."
        else:
            # Fallback to browser search
            webbrowser.open(f"https://stackoverflow.com/search?q={encoded}")
            return f"No exact match found. Opening Stack Overflow search for: {query}"

    except Exception as e:
        webbrowser.open(f"https://stackoverflow.com/search?q={urllib.parse.quote(query)}")
        return f"Opening Stack Overflow search for: {query}"


# ══════════════════════════════════════════════
#  16. DANCE FOR USER
# ══════════════════════════════════════════════
def dance_for_user() -> str:
    """Make Freya perform a random dance animation."""
    import random
    dances = [
        "Denim_Pop_Dance",
        "Joyful_Dance_with_Hand_Sway",
        "Love_You_Pop_Dance",
        "Pod_Baby_Groove",
        "You_Groove",
        "Pop_Dance_LSA2"
    ]
    chosen = random.choice(dances)
    return f"DANCING:{chosen}"

# ══════════════════════════════════════════════
#  17. CAPTURE SCREEN (sends to Gemini)
# ══════════════════════════════════════════════
def capture_screen_tool() -> str:
    """Capture the screen — returns signal for model.py to send image to Gemini."""
    # The actual capture + send happens in model.py
    # This just signals that vision was requested
    return "VISION_REQUESTED"


# ══════════════════════════════════════════════
#  18. MOVE MOUSE (scales coordinates from 1280px grid)
# ══════════════════════════════════════════════
def scale_coords(x: int, y: int) -> tuple[int, int]:
    """Map coordinates from the screenshot grid Gemini saw to real screen pixels.

    Delegates to core.vision.grid_to_screen, which uses the exact capture
    geometry (resized image size vs. physical screen size) recorded during
    the last capture_screen() call. Fixes clicks landing short on wide or
    DPI-scaled displays.
    """
    from core.vision import grid_to_screen
    return grid_to_screen(x, y)


def move_mouse_tool(x: int, y: int) -> str:
    from core.vision import move_mouse
    sx, sy = scale_coords(x, y)
    return move_mouse(sx, sy)


# ══════════════════════════════════════════════
#  19. CLICK (scales coordinates from 1280px grid)
# ══════════════════════════════════════════════
def click_tool(x: int, y: int, button: str = "left", double: bool = False) -> str:
    from core.vision import click
    sx, sy = scale_coords(x, y)
    return click(sx, sy, button, double)


# ══════════════════════════════════════════════
#  20. TYPE TEXT
# ══════════════════════════════════════════════
def type_text_tool(text: str) -> str:
    from core.vision import type_text
    return type_text(text)


# ══════════════════════════════════════════════
#  21. PRESS KEY
# ══════════════════════════════════════════════
def press_key_tool(key: str) -> str:
    from core.vision import press_key
    return press_key(key)


# ══════════════════════════════════════════════
#  22. SCROLL (scales coordinates from 1280px grid)
# ══════════════════════════════════════════════
def scroll_tool(x: int, y: int, direction: str = "down", amount: int = 3) -> str:
    from core.vision import scroll
    sx, sy = scale_coords(x, y)
    return scroll(sx, sy, direction, amount)

# ══════════════════════════════════════════════
#  23. MODE SWITCHER (updates config to change Freya's mode/personality)
# ══════════════════════════════════════════════

def switch_mode(mode: str) -> str:
    """Switch Freya's active mode by updating config."""
    import json, os
    from config import load_config
    try:
        config = load_config()
    except Exception:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'freya_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
            
    valid_modes = list(config.get("modes", {}).keys())
    if "default" not in valid_modes:
        valid_modes.append("default")
        
    if mode not in valid_modes:
        return f"Unknown mode: {mode}. Valid modes are: {', '.join(valid_modes)}"
    
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'freya_config.json')
    try:
        with open(config_path, 'r') as f:
            raw_config = json.load(f)
        raw_config['active_mode'] = mode
        with open(config_path, 'w') as f:
            json.dump(raw_config, f, indent=2)
        return f"MODE_SWITCHED:{mode}"
    except Exception as e:
        return f"Mode switch failed: {str(e)}"


# ══════════════════════════════════════════════
#  TOOL DISPATCHER
#  Called by model.py when Gemini picks a tool
# ══════════════════════════════════════════════
def dispatch(tool_name: str, tool_args: dict, config: dict) -> str:
    """Route a Gemini function call to the correct Python function."""
    try:
        if tool_name == "open_app":
            return open_app(tool_args.get("name", ""), config)
        elif tool_name == "close_app":
            return close_app(tool_args.get("name", ""))
        elif tool_name == "switch_mode":
            return switch_mode(tool_args.get("mode", "default"))
        elif tool_name == "web_search":
            return web_search(tool_args.get("query", ""))
        elif tool_name == "play_youtube":
            return play_youtube(tool_args.get("query", ""))
        elif tool_name == "get_news":
            return get_news(tool_args.get("topic", "world"))
        elif tool_name == "shutdown_computer":
            return shutdown_computer(int(tool_args.get("delay_seconds", 30)))
        elif tool_name == "take_screenshot":
            return take_screenshot()
        elif tool_name == "open_folder":
            return open_folder(tool_args.get("name", ""), config)
        elif tool_name == "get_weather":
            return get_weather(tool_args.get("city", ""))
        elif tool_name == "set_reminder":
            return set_reminder(tool_args.get("message", ""), int(tool_args.get("minutes", 5)))
        elif tool_name == "search_docs":
            return search_docs(tool_args.get("technology", ""), tool_args.get("query", ""))
        elif tool_name == "explain_error":
            return explain_error(tool_args.get("error_text", ""))
        elif tool_name == "open_project":
            return open_project(tool_args.get("project_name", ""), config)
        elif tool_name == "run_terminal_command":
            return run_terminal_command(tool_args.get("command", ""))
        elif tool_name == "search_stackoverflow":
            return search_stackoverflow(tool_args.get("query", ""))
        elif tool_name == "dance_for_user":
            return dance_for_user()
        elif tool_name == "capture_screen":
            return capture_screen_tool()
        elif tool_name == "move_mouse":
            return move_mouse_tool(int(tool_args.get("x", 0)), int(tool_args.get("y", 0)))
        elif tool_name == "click":
            return click_tool(
                int(tool_args.get("x", 0)),
                int(tool_args.get("y", 0)),
                tool_args.get("button", "left"),
                bool(tool_args.get("double", False))
            )
        elif tool_name == "type_text":
            return type_text_tool(tool_args.get("text", ""))
        elif tool_name == "press_key":
            return press_key_tool(tool_args.get("key", ""))
        elif tool_name == "scroll":
            return scroll_tool(
                int(tool_args.get("x", 0)),
                int(tool_args.get("y", 0)),
                tool_args.get("direction", "down"),
                int(tool_args.get("amount", 3))
            )
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        return f"Tool error in {tool_name}: {str(e)}"