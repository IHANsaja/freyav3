"""
Listening-control tool — lets Freya mute her own ears on command.

When the user says he's watching a movie, wants quiet, or "stop listening", she calls
`pause_listening`, which stops the mic from being forwarded to Gemini so ambient audio can't
trigger her. She can't un-pause by voice (she's muted), so resuming is done via the dashboard
button or the global hotkey (Ctrl+Alt+Space).
"""

from core import runtime
from core.registry import tool, OBJ


@tool(
    "pause_listening",
    "Mute your mic so a movie or background noise can't trigger you. Use on 'stop listening', "
    "'quiet', 'I am watching something'. Tell him Ctrl+Alt+Space or Resume brings you back.",
    OBJ(),
)
def pause_listening(args, ctx) -> str:
    runtime.set_paused(True)
    return ("Okay, I'll stop listening so the movie doesn't bother me. Tap Resume on the "
            "dashboard or press Ctrl Alt Space whenever you want me back.")
