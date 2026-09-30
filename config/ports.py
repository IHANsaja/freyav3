"""Which ports this Freya uses.

start-freya.ps1 picks free ports each time it starts - 8000 and 3000 when they
are free, the next free ones when something else (another app, another copy of
Freya) holds them - and passes them in FREYA_API_PORT / FREYA_UI_PORT.
Started any other way, the defaults apply.
"""
import os

DEFAULT_API_PORT = 8000
DEFAULT_UI_PORT = 3000


def _port(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
        return value if 0 < value < 65536 else default
    except ValueError:
        return default


def api_port() -> int:
    """The backend's port."""
    return _port("FREYA_API_PORT", DEFAULT_API_PORT)


def ui_port() -> int:
    """The dashboard's port."""
    return _port("FREYA_UI_PORT", DEFAULT_UI_PORT)


def ui_url(path: str = "") -> str:
    return f"http://localhost:{ui_port()}{path}"


def dashboard_origins() -> list[str]:
    """Browser origins allowed to talk to the backend: the dashboard only."""
    port = ui_port()
    return [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
