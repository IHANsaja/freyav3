import base64
import ctypes
import sys
import threading
import time
from io import BytesIO

import mss
import mss.tools
import pyautogui
from PIL import Image

# ══════════════════════════════════════════════
#  DPI AWARENESS (Windows)
#  Without this, pyautogui reports the *logical* resolution
#  (e.g. 1536x864 at 125% scaling) while mss captures *physical*
#  pixels (1920x1080) — which made every click land short.
# ══════════════════════════════════════════════
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ══════════════════════════════════════════════
#  CAPTURE GEOMETRY STATE
#  Records exactly what Gemini "sees" so grid coordinates can be
#  mapped back to real screen pixels with no guesswork.
# ══════════════════════════════════════════════
_capture_lock = threading.Lock()
_capture_state = {
    "grid_w": None,    # width of the image sent to Gemini
    "grid_h": None,    # height of the image sent to Gemini
    "screen_w": None,  # physical screen size at capture time
    "screen_h": None,
}


def grid_to_screen(x: int, y: int) -> tuple[int, int]:
    """Map a coordinate from Gemini's screenshot grid to real screen pixels.

    Uses the exact geometry recorded by the last capture_screen() call
    (resized image size vs. physical monitor size), so clicks land
    precisely regardless of resolution or Windows DPI scaling.
    """
    with _capture_lock:
        gw, gh = _capture_state["grid_w"], _capture_state["grid_h"]
        sw, sh = _capture_state["screen_w"], _capture_state["screen_h"]

    if not gw or not sw:
        # No capture yet this session — assume the documented 1280-wide grid.
        sw, sh = get_screen_size()
        scale = sw / 1280.0
        return int(round(x * scale)), int(round(y * scale))

    sx = int(round(x * (sw / gw)))
    sy = int(round(y * (sh / gh)))
    return sx, sy


def get_capture_grid() -> tuple[int, int]:
    """Return the size of the last screenshot sent to Gemini (grid pixels)."""
    with _capture_lock:
        gw, gh = _capture_state["grid_w"], _capture_state["grid_h"]
    return (gw or 1280, gh or 720)


# ══════════════════════════════════════════════
#  SCREEN CAPTURE
# ══════════════════════════════════════════════
def capture_screen(quality: int = 60) -> str:
    """
    Capture the full screen and return as base64 encoded JPEG.
    Lower quality = smaller payload = faster to send to Gemini.
    Also records the capture geometry used by grid_to_screen().
    """
    with mss.mss() as sct:
        # Capture primary monitor
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)

        # Convert to PIL Image
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        native_w, native_h = img.width, img.height

        # Resize to reduce payload (Gemini doesn't need full 4K)
        max_width = 1280
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # Record exactly what Gemini will see vs. the real screen
        with _capture_lock:
            _capture_state["grid_w"] = img.width
            _capture_state["grid_h"] = img.height
            _capture_state["screen_w"] = native_w
            _capture_state["screen_h"] = native_h

        # Encode as JPEG base64
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        b64 = base64.b64encode(buffer.read()).decode("utf-8")

        # Show scan effect AFTER capture so it doesn't appear in the screenshot
        try:
            from core.overlay import show_scan_effect
            show_scan_effect()
        except Exception:
            pass

        return b64


def get_screen_size() -> tuple[int, int]:
    """Return current screen resolution (physical pixels, DPI-aware)."""
    size = pyautogui.size()
    return size.width, size.height


# ══════════════════════════════════════════════
#  MOUSE CONTROL  (all coordinates are real screen pixels)
# ══════════════════════════════════════════════
def move_mouse(x: int, y: int) -> str:
    """Move mouse cursor to screen coordinates."""
    try:
        screen_w, screen_h = get_screen_size()
        # Safety clamp to screen bounds
        x = max(0, min(x, screen_w))
        y = max(0, min(y, screen_h))
        pyautogui.moveTo(x, y, duration=0.3)
        try:
            from core.overlay import show_move_effect
            show_move_effect(x, y)
        except Exception:
            pass
        return f"Mouse moved to ({x}, {y})."
    except Exception as e:
        return f"Mouse move failed: {str(e)}"


def click(x: int, y: int, button: str = "left", double: bool = False) -> str:
    """Click at screen coordinates."""
    try:
        screen_w, screen_h = get_screen_size()
        x = max(0, min(x, screen_w))
        y = max(0, min(y, screen_h))

        if double:
            pyautogui.doubleClick(x, y)
            result = f"Double clicked at ({x}, {y})."
        else:
            pyautogui.click(x, y, button=button)
            result = f"{button.capitalize()} clicked at ({x}, {y})."
        try:
            from core.overlay import show_click_effect
            show_click_effect(x, y)
        except Exception:
            pass
        return result
    except Exception as e:
        return f"Click failed: {str(e)}"


def type_text(text: str, interval: float = 0.05) -> str:
    """Type text using keyboard."""
    try:
        # Small delay to ensure focus
        time.sleep(0.2)
        pyautogui.typewrite(text, interval=interval)
        try:
            from core.overlay import show_type_effect
            show_type_effect()
        except Exception:
            pass
        return f"Typed: {text}"
    except Exception as e:
        # Fallback for unicode characters
        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            return f"Typed (via clipboard): {text}"
        except:
            return f"Type failed: {str(e)}"


def press_key(key: str) -> str:
    """Press a keyboard key or hotkey combination."""
    try:
        # Handle combos like "ctrl+c", "ctrl+shift+t"
        if "+" in key:
            keys = [k.strip() for k in key.split("+")]
            pyautogui.hotkey(*keys)
            return f"Pressed hotkey: {key}"
        else:
            pyautogui.press(key)
            return f"Pressed key: {key}"
    except Exception as e:
        return f"Key press failed: {str(e)}"


def scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> str:
    """Scroll at screen coordinates."""
    try:
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks, x=x, y=y)
        try:
            from core.overlay import show_scroll_effect
            show_scroll_effect(x, y, direction)
        except Exception:
            pass
        return f"Scrolled {direction} {amount} times at ({x}, {y})."
    except Exception as e:
        return f"Scroll failed: {str(e)}"