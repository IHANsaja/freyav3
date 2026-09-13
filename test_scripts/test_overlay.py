"""
Preview the GPU shader overlay without running Freya.

Run from the project root:
    venv\\Scripts\\python.exe test_scripts\\test_overlay.py            # all six effects
    venv\\Scripts\\python.exe test_scripts\\test_overlay.py click      # just one
    venv\\Scripts\\python.exe test_scripts\\test_overlay.py --loop     # repeat forever

Fires every effect in turn so you can actually look at them — the GPU path cannot be
checked from an assertion, only with your eyes. Falls back to the tkinter effects if a GL
context can't be created. Ctrl+C to exit.

Also prints the measured present-path cost per frame, which is the number that decides how
heavy the shaders are allowed to get: the framebuffer is read back to the CPU every frame.
"""

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure DPI awareness matches the real control path (sets physical-pixel coords).
import core.vision  # noqa: F401  (import side effect: SetProcessDpiAwareness)
from core import overlay

user32 = ctypes.windll.user32
SM_XVIRTUAL, SM_YVIRTUAL, SM_CXVIRTUAL, SM_CYVIRTUAL = 76, 77, 78, 79

PW, PH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
VX, VY = user32.GetSystemMetrics(SM_XVIRTUAL), user32.GetSystemMetrics(SM_YVIRTUAL)
VW, VH = user32.GetSystemMetrics(SM_CXVIRTUAL), user32.GetSystemMetrics(SM_CYVIRTUAL)
MULTI = (VW, VH) != (PW, PH)


def demo_scan():
    print("  scan        — capture frame (brackets the PRIMARY monitor only)")
    overlay.show_scan_effect()
    time.sleep(1.6)


def demo_element():
    print("  element     — target lock on three boxes")
    for r in ((int(PW * 0.15), int(PH * 0.25), int(PW * 0.32), int(PH * 0.31)),
              (int(PW * 0.45), int(PH * 0.45), int(PW * 0.62), int(PH * 0.52)),
              (int(PW * 0.70), int(PH * 0.62), int(PW * 0.88), int(PH * 0.70))):
        overlay.show_element_effect(r)
        time.sleep(1.3)


def demo_click():
    print("  click       — impact bursts")
    for i in range(5):
        overlay.show_click_effect(int(PW * (0.2 + i * 0.15)), int(PH * 0.8))
        time.sleep(0.55)
    time.sleep(0.8)


def demo_move():
    print("  move        — cursor trail across the screen")
    for i in range(22):
        t = i / 21.0
        overlay.show_move_effect(int(PW * (0.1 + 0.8 * t)),
                                 int(PH * (0.5 + 0.18 * (t - 0.5) ** 2 * 8)))
        time.sleep(0.06)
    time.sleep(1.0)


def demo_scroll():
    print("  scroll      — down, then up (they should look different)")
    overlay.show_scroll_effect(int(PW * 0.5), int(PH * 0.5), "down")
    time.sleep(1.4)
    overlay.show_scroll_effect(int(PW * 0.5), int(PH * 0.5), "up")
    time.sleep(1.4)


def demo_type():
    print("  type        — caret + data blocks (NOT the capture frame)")
    overlay.show_type_effect(int(PW * 0.35), int(PH * 0.45))
    time.sleep(1.4)


def demo_multi():
    if not MULTI:
        print("  multi       — skipped, only one monitor detected")
        return
    print(f"  multi       — second monitor: virtual desktop is {VW}x{VH} at ({VX},{VY})")
    # A box on whatever is furthest from the primary origin.
    x = VX + 60 if VX < 0 else VX + VW - 400
    overlay.show_element_effect((x, VY + 120, x + 340, VY + 220))
    time.sleep(1.4)
    overlay.show_click_effect(x + 170, VY + 320)
    time.sleep(1.2)


DEMOS = {
    "scan": demo_scan, "element": demo_element, "click": demo_click,
    "move": demo_move, "scroll": demo_scroll, "type": demo_type, "multi": demo_multi,
}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    loop = "--loop" in sys.argv

    print(f"Primary: {PW}x{PH}   Virtual: {VW}x{VH} at ({VX},{VY})"
          f"{'   [MULTI-MONITOR]' if MULTI else ''}")

    backend = overlay._gpu_backend()
    print("Backend:", "GPU shader (core/shaders/*.glsl)" if backend else "tkinter fallback")
    if not backend:
        print("  NOTE: GL context unavailable — you are seeing the plain Canvas fallback,")
        print("        not the shaders. Nothing below reflects the real look.")

    chosen = [DEMOS[a] for a in args if a in DEMOS] or list(DEMOS.values())
    unknown = [a for a in args if a not in DEMOS]
    if unknown:
        print(f"  unknown effect(s) {unknown}; known: {', '.join(DEMOS)}")

    print("\nWatch your screen. Ctrl+C to stop.\n")
    try:
        while True:
            for fn in chosen:
                fn()
            if backend:
                try:
                    from core import shader_overlay
                    ms = shader_overlay.frame_ms()
                    if ms:
                        print(f"\n  present path: {ms:.2f} ms/frame "
                              f"({1000.0 / ms:.0f} fps ceiling) at {VW}x{VH}")
                except Exception:
                    pass
            if not loop:
                break
            print("\n--- looping ---\n")
        print("\nDone. Holding 2s so the last effect finishes...")
        time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            from core import shader_overlay
            shader_overlay.stop()
        except Exception:
            pass
        print("Overlay stopped.")


if __name__ == "__main__":
    main()
