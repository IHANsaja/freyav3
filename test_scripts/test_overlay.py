"""
Preview the GPU shader overlay ("Crimson Core Sync") without running Freya.

Run from the project root:
    venv\\Scripts\\python.exe test_scripts\\test_overlay.py

It fires a scan sweep, a few element lock-ons, and click pulses across your screen so you
can see the effect. If the GPU overlay can't initialize it automatically falls back to the
tkinter effects. Press Ctrl+C in the terminal to exit.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure DPI awareness matches the real control path (sets physical-pixel coords).
import core.vision  # noqa: F401  (import side effect: SetProcessDpiAwareness)
from core import overlay

import ctypes
SW = ctypes.windll.user32.GetSystemMetrics(0)
SH = ctypes.windll.user32.GetSystemMetrics(1)

print(f"Screen: {SW}x{SH}")
print("Firing overlay effects... watch your screen. Ctrl+C to stop.")

# Force backend probe up front so we know which path is used.
backend = overlay._gpu_backend()
print("Backend:", "GPU shader (Crimson Core Sync)" if backend else "tkinter fallback")

try:
    overlay.show_scan_effect()
    time.sleep(1.2)

    # A row of fake "elements" to lock onto
    boxes = [
        (int(SW * 0.15), int(SH * 0.25), int(SW * 0.32), int(SH * 0.31)),
        (int(SW * 0.45), int(SH * 0.45), int(SW * 0.62), int(SH * 0.52)),
        (int(SW * 0.70), int(SH * 0.65), int(SW * 0.88), int(SH * 0.72)),
    ]
    for r in boxes:
        overlay.show_element_effect(r)
        time.sleep(1.1)

    for i in range(5):
        overlay.show_click_effect(int(SW * (0.2 + i * 0.15)), int(SH * 0.8))
        time.sleep(0.6)

    print("Done. Holding 3s so the last effects finish...")
    time.sleep(3)
except KeyboardInterrupt:
    pass
finally:
    # Tear the overlay window down cleanly (no alt+F4 needed).
    try:
        from core import shader_overlay
        shader_overlay.stop()
    except Exception:
        pass
    print("Overlay stopped.")
