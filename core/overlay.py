"""
Visual overlay effects for Freya's screen control actions.
Renders transparent, always-on-top animations using tkinter
to give real-time visual feedback when Freya interacts with the screen.

Effects:
  - Click ripple with crosshair
  - Screen scan border flash + sweep line
  - Mouse-move pulse dot
  - Scroll direction arrow
  - Typing indicator badge
"""

import threading
import tkinter as tk
import queue

# ── Freya theme colours ──
FREYA_RED = '#ff3333'
FREYA_RED_DIM = '#cc2222'
TRANSPARENT_BG = '#010101'   # used as the invisible colour on Windows


# ══════════════════════════════════════════════
#  SINGLETON ACCESS
# ══════════════════════════════════════════════
_instance = None
_lock = threading.Lock()


def _get():
    global _instance
    with _lock:
        if _instance is None:
            _instance = OverlayManager()
    return _instance


# ══════════════════════════════════════════════
#  PUBLIC API  (safe to call from any thread)
# ══════════════════════════════════════════════
def show_click_effect(x: int, y: int):
    try: _get().enqueue({'type': 'click', 'x': x, 'y': y})
    except Exception: pass

def show_scan_effect():
    try: _get().enqueue({'type': 'scan'})
    except Exception: pass

def show_move_effect(x: int, y: int):
    try: _get().enqueue({'type': 'move', 'x': x, 'y': y})
    except Exception: pass

def show_scroll_effect(x: int, y: int, direction: str):
    try: _get().enqueue({'type': 'scroll', 'x': x, 'y': y, 'direction': direction})
    except Exception: pass

def show_type_effect():
    try: _get().enqueue({'type': 'type'})
    except Exception: pass


# ══════════════════════════════════════════════
#  OVERLAY MANAGER
#  Runs tkinter in a dedicated daemon thread.
#  Commands arrive via a thread-safe queue.
# ══════════════════════════════════════════════
class OverlayManager:

    def __init__(self):
        self._queue = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def enqueue(self, cmd: dict):
        self._queue.put(cmd)

    # ── tkinter thread ──────────────────────
    def _run(self):
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.attributes('-alpha', 0)
        self._ready.set()
        self._poll()
        self._root.mainloop()

    def _poll(self):
        try:
            while True:
                cmd = self._queue.get_nowait()
                self._dispatch(cmd)
        except queue.Empty:
            pass
        self._root.after(50, self._poll)

    def _dispatch(self, cmd):
        t = cmd['type']
        try:
            if t == 'click':
                self._effect_click(cmd['x'], cmd['y'])
            elif t == 'scan':
                self._effect_scan()
            elif t == 'move':
                self._effect_move(cmd['x'], cmd['y'])
            elif t == 'scroll':
                self._effect_scroll(cmd['x'], cmd['y'], cmd['direction'])
            elif t == 'type':
                self._effect_type()
        except Exception as e:
            print(f"  Overlay error: {e}")

    # ─────────────────────────────────────────
    #  CLICK — expanding crosshair + ripple
    # ─────────────────────────────────────────
    def _effect_click(self, x, y):
        size = 80
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.attributes('-transparentcolor', TRANSPARENT_BG)
        win.geometry(f'{size}x{size}+{x - size // 2}+{y - size // 2}')
        win.config(bg=TRANSPARENT_BG)

        canvas = tk.Canvas(win, width=size, height=size,
                           bg=TRANSPARENT_BG, highlightthickness=0)
        canvas.pack()
        self._anim_click(win, canvas, size // 2, 0)

    def _anim_click(self, win, canvas, c, step):
        if step > 14:
            try: win.destroy()
            except: pass
            return

        canvas.delete('all')

        # Outer expanding ring
        r = 5 + step * 2.5
        w = max(1, 3 - step // 5)
        canvas.create_oval(c - r, c - r, c + r, c + r,
                           outline=FREYA_RED, width=w)

        # Delayed second ring
        if step > 3:
            r2 = 5 + (step - 3) * 2.5
            canvas.create_oval(c - r2, c - r2, c + r2, c + r2,
                               outline=FREYA_RED_DIM, width=1)

        # Centre dot
        if step < 10:
            canvas.create_oval(c - 3, c - 3, c + 3, c + 3,
                               fill=FREYA_RED, outline='')

        # Crosshair arms
        if step < 8:
            gap, arm = 6, 12
            canvas.create_line(c - arm, c, c - gap, c, fill=FREYA_RED, width=1)
            canvas.create_line(c + gap, c, c + arm, c, fill=FREYA_RED, width=1)
            canvas.create_line(c, c - arm, c, c - gap, fill=FREYA_RED, width=1)
            canvas.create_line(c, c + gap, c, c + arm, fill=FREYA_RED, width=1)

        win.after(30, self._anim_click, win, canvas, c, step + 1)

    # ─────────────────────────────────────────
    #  SCAN — red border flash + sweep line
    # ─────────────────────────────────────────
    def _effect_scan(self):
        import pyautogui
        sw, sh = pyautogui.size()
        border = 3

        # Four border bars
        specs = [
            (sw, border, 0, 0),              # top
            (sw, border, 0, sh - border),     # bottom
            (border, sh, 0, 0),              # left
            (border, sh, sw - border, 0),    # right
        ]
        for w, h, x, y in specs:
            win = tk.Toplevel(self._root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.geometry(f'{w}x{h}+{x}+{y}')
            win.config(bg=FREYA_RED)
            win.attributes('-alpha', 0.85)
            self._fade_out(win, 0, 0.085)

        # Horizontal scan line sweeping top → bottom
        line_h = 2
        scan = tk.Toplevel(self._root)
        scan.overrideredirect(True)
        scan.attributes('-topmost', True)
        scan.geometry(f'{sw}x{line_h}+0+0')
        scan.config(bg=FREYA_RED)
        scan.attributes('-alpha', 0.6)
        self._sweep(scan, 0, sh, sw, line_h)

        # "👁 SCANNING" badge at top centre
        badge_w, badge_h = 180, 28
        badge = tk.Toplevel(self._root)
        badge.overrideredirect(True)
        badge.attributes('-topmost', True)
        badge.geometry(f'{badge_w}x{badge_h}+{sw // 2 - badge_w // 2}+8')
        badge.config(bg='#1a1a2e')
        label = tk.Label(badge, text='👁  FREYA SCANNING',
                         font=('Consolas', 9, 'bold'),
                         fg=FREYA_RED, bg='#1a1a2e')
        label.pack(expand=True)
        self._fade_out(badge, 0, 0.10, start_alpha=0.95, delay=80)

    def _fade_out(self, win, step, rate, start_alpha=0.85, delay=50):
        if step > 10:
            try: win.destroy()
            except: pass
            return
        alpha = max(0.05, start_alpha - step * rate)
        try: win.attributes('-alpha', alpha)
        except: pass
        win.after(delay, self._fade_out, win, step + 1, rate, start_alpha, delay)

    def _sweep(self, win, y, max_y, sw, line_h):
        if y >= max_y:
            try: win.destroy()
            except: pass
            return
        try: win.geometry(f'{sw}x{line_h}+0+{y}')
        except: return
        step = max(4, int((max_y - y) * 0.025) + 4)
        win.after(5, self._sweep, win, y + step, max_y, sw, line_h)

    # ─────────────────────────────────────────
    #  MOVE — pulsing dot at destination
    # ─────────────────────────────────────────
    def _effect_move(self, x, y):
        size = 30
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.attributes('-transparentcolor', TRANSPARENT_BG)
        win.geometry(f'{size}x{size}+{x - size // 2}+{y - size // 2}')
        win.config(bg=TRANSPARENT_BG)

        canvas = tk.Canvas(win, width=size, height=size,
                           bg=TRANSPARENT_BG, highlightthickness=0)
        canvas.pack()

        c = size // 2
        canvas.create_oval(c - 6, c - 6, c + 6, c + 6,
                           outline=FREYA_RED, width=2)
        canvas.create_oval(c - 2, c - 2, c + 2, c + 2,
                           fill=FREYA_RED, outline='')

        self._alpha_fade(win, 0)

    def _alpha_fade(self, win, step):
        if step > 8:
            try: win.destroy()
            except: pass
            return
        alpha = max(0.05, 1.0 - step * 0.125)
        try: win.attributes('-alpha', alpha)
        except: pass
        win.after(40, self._alpha_fade, win, step + 1)

    # ─────────────────────────────────────────
    #  SCROLL — directional arrow
    # ─────────────────────────────────────────
    def _effect_scroll(self, x, y, direction):
        w, h = 40, 50
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.attributes('-transparentcolor', TRANSPARENT_BG)
        win.geometry(f'{w}x{h}+{x - w // 2}+{y - h // 2}')
        win.config(bg=TRANSPARENT_BG)

        canvas = tk.Canvas(win, width=w, height=h,
                           bg=TRANSPARENT_BG, highlightthickness=0)
        canvas.pack()

        cx, cy = w // 2, h // 2
        if direction == 'up':
            canvas.create_polygon(cx, cy - 15, cx - 10, cy + 5, cx + 10, cy + 5,
                                  fill=FREYA_RED, outline='')
            canvas.create_line(cx, cy + 5, cx, cy + 18,
                               fill=FREYA_RED, width=2)
        else:
            canvas.create_polygon(cx, cy + 15, cx - 10, cy - 5, cx + 10, cy - 5,
                                  fill=FREYA_RED, outline='')
            canvas.create_line(cx, cy - 5, cx, cy - 18,
                               fill=FREYA_RED, width=2)

        self._alpha_fade(win, 0)

    # ─────────────────────────────────────────
    #  TYPE — keyboard badge
    # ─────────────────────────────────────────
    def _effect_type(self):
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.geometry('140x28+20+20')
        win.config(bg='#1a1a2e')

        label = tk.Label(win, text='⌨  FREYA TYPING',
                         font=('Consolas', 9, 'bold'),
                         fg=FREYA_RED, bg='#1a1a2e')
        label.pack(expand=True)

        self._fade_out(win, 0, 0.10, start_alpha=0.95, delay=100)
