"""
Listening-control tool — lets Freya mute her own ears on command.

When Ihan says he's watching a movie, wants quiet, or "stop listening", she calls
`pause_listening`, which stops the mic from being forwarded to Gemini so ambient audio can't
trigger her. She can't un-pause by voice (she's muted), so resuming is done via the dashboard
button or the global hotkey (Ctrl+Alt+Space).
"""

from core import runtime
from core.registry import tool, OBJ


@tool(
    "pause_listening",
    "Mute your own listening (stop the mic) so a movie or background sound doesn't make you "
    "respond. Use when Ihan says he's watching something, wants quiet, says 'stop listening', "
    "'pause', 'mute yourself', etc. Tell him you'll stop, and that he can tap Resume on the "
    "dashboard or press Ctrl+Alt+Space to bring you back.",
    OBJ(),
)
def pause_listening(args, ctx) -> str:
    runtime.set_paused(True)
    return ("Okay, I'll stop listening so the movie doesn't bother me. Tap Resume on the "
            "dashboard or press Ctrl Alt Space whenever you want me back.")
