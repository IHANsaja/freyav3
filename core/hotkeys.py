"""
Global hotkey to toggle Freya's mic pause — so you can mute/unmute her listening even when
she's paused (she can't hear a voice "resume" once muted). Default: Ctrl+Alt+Space.

Uses the `keyboard` library (already a dependency). Registered once; the model's send_audio
loop notices the flag flip and broadcasts the new state to the dashboard.
"""

import threading

_registered = False
_lock = threading.Lock()


def start_pause_hotkey(config: dict):
    global _registered
    with _lock:
        if _registered:
            return
        combo = (config or {}).get("freya", {}).get("pause_hotkey", "ctrl+alt+space")
        try:
            import keyboard
        except Exception as e:
            print(f"  [hotkeys] 'keyboard' unavailable, pause hotkey disabled: {e}")
            return

        def _toggle():
            from core import runtime
            paused = runtime.toggle_paused()
            print("  🔇 Mic paused (hotkey)." if paused else "  🔊 Mic resumed (hotkey).")

        try:
            keyboard.add_hotkey(combo, _toggle)
            _registered = True
            print(f"  Pause-listening hotkey active: {combo}")
        except Exception as e:
            print(f"  [hotkeys] couldn't register {combo}: {e}")
