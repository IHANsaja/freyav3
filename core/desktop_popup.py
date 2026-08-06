"""
Desktop popup cards — Freya speaking up while you're in another window.

Why this exists
---------------
Everything Freya retrieves from the web (`show_image`, `show_info`, mission
findings, scheduled briefings) used to land on the dashboard canvas only. That's
fine while the dashboard is the focused window and useless the rest of the time,
which is most of the time: background missions, the scheduler and the ambient
watcher all produce their best material precisely when the user is doing
something else.

This module renders those same cards as small always-on-top toasts stacked down
the RIGHT edge of the primary monitor, over whatever app is in front. They slide
in, hold, then fade out. Hovering pauses the countdown (so a long snippet can
actually be read); clicking dismisses immediately.

How it's driven
---------------
`attach_to_bus(config)` subscribes to the event bus, so any part of Freya that
already calls `runtime.emit("card"|"image", ...)` reaches the desktop for free —
no voice session and no open browser tab required. Events opt in with
`popup: True` in their payload, so a routine screen capture doesn't throw a
toast in the user's face.

Threading
---------
tkinter is not thread-safe, so all widget work happens on ONE dedicated daemon
thread with its own `Tk` root, fed by a queue — the same pattern core/overlay.py
uses for its click/scan effects. Each root only ever touches its own widgets,
which is the condition under which multiple roots in one process are safe.
"""

import base64
import ctypes
import queue
import threading
import time
import tkinter as tk
from io import BytesIO

# ── Freya theme ──
BG = "#0b0f0d"
BG_ALT = "#111814"
ACCENT = "#0f9c6e"
TEXT = "#e8f2ec"
MUTED = "#7d8c85"

CARD_W = 340
IMG_H = 150
MARGIN = 18          # gap from the screen edges
GAP = 12             # gap between stacked cards
DEFAULT_MS = 14000   # how long a card holds before fading
MAX_VISIBLE = 3      # older cards are retired when a 4th arrives

_manager = None
_lock = threading.Lock()
_unsubscribe = None


# ══════════════════════════════════════════════
#  PUBLIC API  (safe to call from any thread)
# ══════════════════════════════════════════════
def show(title: str, body: str = "", source: str = "", image_b64: str | None = None,
         duration_ms: int | None = None) -> bool:
    """Pop a card on the desktop. Returns False if the popup layer is unusable
    (headless session, no display, tkinter missing) — callers treat that as a
    soft failure, since the dashboard copy of the card still went out."""
    try:
        mgr = _get()
    except Exception as e:
        print(f"  [popup] unavailable: {e}")
        return False
    if mgr is None:
        return False
    mgr.enqueue({
        "title": (title or "Freya").strip(),
        "body": (body or "").strip(),
        "source": (source or "").strip(),
        "image": image_b64,
        "duration": int(duration_ms or DEFAULT_MS),
    })
    return True


def configure(config: dict | None):
    """Apply the `desktop_popup` config block (duration, width, max visible)."""
    global CARD_W, DEFAULT_MS, MAX_VISIBLE
    cfg = ((config or {}).get("desktop_popup") or {})
    CARD_W = int(cfg.get("width", CARD_W))
    DEFAULT_MS = int(cfg.get("duration_ms", DEFAULT_MS))
    MAX_VISIBLE = int(cfg.get("max_visible", MAX_VISIBLE))


def enabled(config: dict | None) -> bool:
    cfg = ((config or {}).get("desktop_popup") or {})
    return bool(cfg.get("enabled", True))


def attach_to_bus(config: dict | None):
    """Mirror `card` / `image` bus events onto the desktop.

    Returns an unsubscribe callable (a no-op if popups are disabled), so the
    caller's shutdown path can detach cleanly.
    """
    global _unsubscribe
    if not enabled(config):
        return lambda: None
    configure(config)

    from core.events import bus

    async def _listener(event):
        p = event.payload or {}
        if not p.get("popup"):
            return
        if event.type == "card":
            show(p.get("title", "Freya"), p.get("body", ""), p.get("source", ""),
                 p.get("image"), p.get("durationMs"))
        elif event.type == "image":
            show(p.get("label", "Image"), "", p.get("source", ""), p.get("data"))

    _unsubscribe = bus.subscribe(_listener)
    return _unsubscribe


def shutdown():
    """Detach from the bus and tear the popup thread down."""
    global _unsubscribe, _manager
    if _unsubscribe:
        try:
            _unsubscribe()
        except Exception:
            pass
        _unsubscribe = None
    with _lock:
        if _manager is not None:
            _manager.enqueue({"__quit__": True})
            _manager = None


# ══════════════════════════════════════════════
#  INTERNALS
# ══════════════════════════════════════════════
def _get():
    global _manager
    with _lock:
        if _manager is None:
            _manager = _PopupManager()
        return _manager


def _work_area() -> tuple[int, int, int, int] | None:
    """Primary monitor work area (left, top, right, bottom) — i.e. the screen
    minus the taskbar, so a card never hides behind it. Falls back to the full
    screen when the Win32 call isn't available."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        # SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return None


class _PopupManager:
    """Owns the tk root and the live stack of cards. All methods below the
    `enqueue` boundary run on the tk thread only."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._cards: list["_Card"] = []
        self._thread = threading.Thread(target=self._run, daemon=True, name="freya-popup")
        self._thread.start()
        self._ready.wait(timeout=4)
        if self._error:
            raise self._error

    def enqueue(self, cmd: dict):
        self._queue.put(cmd)

    # ── tk thread ──────────────────────────────
    def _run(self):
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            self._root.attributes("-alpha", 0)
        except Exception as e:
            self._error = e
            self._ready.set()
            return
        self._ready.set()
        self._poll()
        self._root.mainloop()

    def _poll(self):
        try:
            while True:
                cmd = self._queue.get_nowait()
                if cmd.get("__quit__"):
                    try:
                        self._root.quit()
                    except Exception:
                        pass
                    return
                try:
                    self._spawn(cmd)
                except Exception as e:
                    print(f"  [popup] render failed: {e}")
        except queue.Empty:
            pass
        self._root.after(60, self._poll)

    def _spawn(self, cmd: dict):
        while len(self._cards) >= max(1, MAX_VISIBLE):
            self._cards[0].close()          # retires the oldest, triggers a relayout
        card = _Card(self, cmd)
        self._cards.append(card)
        self._relayout()

    def _forget(self, card: "_Card"):
        try:
            self._cards.remove(card)
        except ValueError:
            return
        self._relayout()

    def _relayout(self):
        """Stack cards bottom-up along the right edge. Recomputed whenever one
        appears or dies so a dismissed card never leaves a hole."""
        area = _work_area()
        if area:
            _, _, right, bottom = area
        else:
            right = self._root.winfo_screenwidth()
            bottom = self._root.winfo_screenheight() - 48
        x = right - CARD_W - MARGIN
        y = bottom - MARGIN
        for card in reversed(self._cards):   # newest sits closest to the bottom
            h = card.height()
            y -= h
            card.place(x, y)
            y -= GAP


class _Card:
    """One toast: slide in from the right, hold (pausing while hovered), fade out."""

    def __init__(self, mgr: _PopupManager, data: dict):
        self.mgr = mgr
        self.duration = data["duration"]
        self.hovered = False
        self.closing = False
        self._photo = None      # PhotoImage ref — dropping it would blank the image
        self._x = 0
        self._y = 0

        win = tk.Toplevel(mgr._root)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.0)
        win.config(bg=ACCENT)

        # 1px accent frame around a dark body.
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(body, bg=BG_ALT)
        header.pack(fill="x")
        tk.Label(header, text="◆", font=("Segoe UI", 9), fg=ACCENT, bg=BG_ALT).pack(side="left", padx=(10, 4), pady=6)
        tk.Label(header, text="FREYA", font=("Segoe UI Semibold", 8), fg=ACCENT, bg=BG_ALT).pack(side="left", pady=6)
        tk.Label(header, text="✕", font=("Segoe UI", 9), fg=MUTED, bg=BG_ALT).pack(side="right", padx=10, pady=6)

        img = self._decode(data.get("image"))
        if img is not None:
            self._photo = img
            tk.Label(body, image=img, bg=BG, bd=0).pack(fill="x")

        pad = tk.Frame(body, bg=BG)
        pad.pack(fill="both", expand=True, padx=12, pady=(9, 11))

        tk.Label(pad, text=data["title"][:140], font=("Segoe UI Semibold", 10),
                 fg=TEXT, bg=BG, wraplength=CARD_W - 30, justify="left",
                 anchor="w").pack(fill="x")

        if data["body"]:
            tk.Label(pad, text=data["body"][:600], font=("Segoe UI", 9),
                     fg=TEXT, bg=BG, wraplength=CARD_W - 30, justify="left",
                     anchor="w").pack(fill="x", pady=(5, 0))

        if data["source"]:
            tk.Label(pad, text=data["source"][:90].upper(), font=("Segoe UI", 7),
                     fg=MUTED, bg=BG, wraplength=CARD_W - 30, justify="left",
                     anchor="w").pack(fill="x", pady=(7, 0))

        # Bind on every descendant: a click on the title label must dismiss too.
        self._bind_all(win)

        win.update_idletasks()
        self._h = win.winfo_reqheight()
        self._born = time.time()
        self._fade_in(0)
        win.after(self.duration, self._maybe_close)

    # ── layout ──
    def height(self) -> int:
        return self._h

    def place(self, x: int, y: int):
        self._x, self._y = x, y
        try:
            self.win.geometry(f"{CARD_W}x{self._h}+{x}+{y}")
        except tk.TclError:
            pass

    # ── behaviour ──
    def _bind_all(self, widget):
        widget.bind("<Button-1>", lambda _e: self.close())
        widget.bind("<Enter>", lambda _e: setattr(self, "hovered", True))
        widget.bind("<Leave>", lambda _e: setattr(self, "hovered", False))
        for child in widget.winfo_children():
            self._bind_all(child)

    def _decode(self, b64: str | None):
        if not b64:
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
            inner = CARD_W - 2
            # Cover-crop to a fixed banner so cards keep a predictable height.
            scale = max(inner / img.width, IMG_H / img.height)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                             Image.LANCZOS)
            left = (img.width - inner) // 2
            top = (img.height - IMG_H) // 2
            img = img.crop((left, top, left + inner, top + IMG_H))
            return ImageTk.PhotoImage(img, master=self.win)
        except Exception as e:
            print(f"  [popup] image skipped: {e}")
            return None

    def _fade_in(self, step: int):
        if self.closing:
            return
        if step > 8:
            return
        try:
            self.win.attributes("-alpha", min(0.96, step * 0.12))
        except tk.TclError:
            return
        # Slide the last few pixels in from the right as it fades up.
        offset = int((8 - step) * 4)
        try:
            self.win.geometry(f"{CARD_W}x{self._h}+{self._x + offset}+{self._y}")
        except tk.TclError:
            return
        self.win.after(22, self._fade_in, step + 1)

    def _maybe_close(self):
        """Hold the card open while the pointer is on it — a 600-char snippet
        takes longer to read than the default dwell."""
        if self.hovered:
            self.win.after(1200, self._maybe_close)
            return
        self.close()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.mgr._forget(self)
        self._fade_out(0)

    def _fade_out(self, step: int):
        if step > 7:
            try:
                self.win.destroy()
            except Exception:
                pass
            return
        try:
            self.win.attributes("-alpha", max(0.0, 0.96 - step * 0.14))
        except tk.TclError:
            return
        self.win.after(20, self._fade_out, step + 1)
