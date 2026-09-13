"""
GPU shader overlay — Freya's screen-control effects.

A transparent, click-through, always-on-top layer that renders real GLSL onto the live
Windows desktop so you can SEE what Freya is doing as she operates the machine. The
control engine (core/screen.py) hands us each element's exact bounding rectangle from UI
Automation, so effects lock onto the REAL element rather than approximating it.

The shaders are real files under core/shaders/, not string literals — see _load_program.
GLSL 330 has no #include, so the loader resolves them host-side and injects MAX_FX and
FX_LIFE as #defines, which is what stops the array sizes drifting away from the Python
constants (they used to be hardcoded four separate times inside the shader).

Transparency approach: render OFFSCREEN with a moderngl standalone context, then present
through `UpdateLayeredWindow` with a per-pixel-alpha DIB. This is the only method that
reliably gives true soft-glow transparency over the desktop — color-key and DWM-extend both
fail with OpenGL (they show an opaque black screen). The window is WS_EX_LAYERED +
WS_EX_TRANSPARENT so it is fully click-through and never blocks Freya's own clicks.

Present path: the fragment shader emits PREMULTIPLIED BGRA in the DIB's own row order, and
we read straight into a preallocated buffer. That leaves one GPU readback plus one memmove
per frame. It used to be a readback plus three full-frame numpy passes (~1.1 GB/s at
1080p), which was the real ceiling on how heavy the shaders could get.

If anything fails to initialize, `start()` returns False and the caller falls back to the
tkinter overlay — this module never hard-crashes Freya. Coordinates are physical screen
pixels spanning the whole virtual desktop (the process is PER_MONITOR_DPI_AWARE via
core/vision).
"""

import atexit
import ctypes
import os
import re
import threading
import time
from ctypes import wintypes
import queue

# ── effect kinds ──
# These MUST match the K_* constants in core/shaders/overlay.frag.
#
# Named K_* deliberately. They used to be ELEMENT/POINT/SCAN, and `POINT` was then
# rebound further down this module to a ctypes struct — so float(POINT) raised, a bare
# `except` swallowed it, and click/move/scroll never rendered once in the life of the file.
K_ELEMENT, K_CLICK, K_MOVE, K_SCROLL, K_SCAN, K_TYPE = 0.0, 1.0, 2.0, 3.0, 4.0, 5.0

LIFE = 1.15          # seconds an effect lives
MAX_FX = 12          # max simultaneous effects (also the shader's array size)
DEFAULT_FPS = 60

_SHADER_DIR = os.path.join(os.path.dirname(__file__), "shaders")
_INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+)"\s*$', re.M)

# ── Win32 plumbing ──
LRESULT = ctypes.c_ssize_t
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

# GetSystemMetrics indices
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class WinPoint(ctypes.Structure):
    """Win32 POINT. Named WinPoint so it can never again collide with an effect-kind
    constant — that collision silently disabled three effects."""
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _sig():
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(WinPoint), ctypes.POINTER(SIZE),
        wintypes.HDC, ctypes.POINTER(WinPoint), wintypes.DWORD,
        ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]


# ── shader loading ────────────────────────────────────────────────────────
def _resolve_includes(path: str, seen=None, sources=None) -> str:
    """Expand `#include "..."` relative to core/shaders/.

    GLSL 330 has no include directive, so this has to happen host-side. Cycles are
    skipped rather than raising: a self-include is a typo, not a reason to lose the
    whole overlay.
    """
    seen = set() if seen is None else seen
    sources = [] if sources is None else sources
    full = os.path.normcase(os.path.abspath(path))
    if full in seen:
        return ""
    seen.add(full)
    sources.append(full)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    def sub(m):
        inc = os.path.join(_SHADER_DIR, m.group(1))
        if not os.path.isfile(inc):
            raise FileNotFoundError(f"#include \"{m.group(1)}\" not found ({inc})")
        return _resolve_includes(inc, seen, sources)

    return _INCLUDE_RE.sub(sub, text)


def _shader_sources() -> tuple[str, str, list[str]]:
    """(vertex, fragment, files) with includes expanded and constants injected."""
    files: list[str] = []
    vert = _resolve_includes(os.path.join(_SHADER_DIR, "overlay.vert"), None, files)
    frag = _resolve_includes(os.path.join(_SHADER_DIR, "overlay.frag"), None, files)

    # Inject after the #version line — nothing may precede it in GLSL.
    defines = f"#define MAX_FX {MAX_FX}\n#define FX_LIFE {LIFE:.4f}\n"
    lines = frag.split("\n")
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("#version"):
            lines.insert(i + 1, defines)
            break
    else:
        raise RuntimeError("overlay.frag has no #version directive")
    return vert, "\n".join(lines), files


def _hex_rgb(value: str, fallback=(1.0, 0.20, 0.18)) -> tuple[float, float, float]:
    try:
        s = str(value).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
    except Exception:
        return fallback


# ── live config ───────────────────────────────────────────────────────────
# Mirrors core/safety.py's _live_safety(): re-read from disk, cached on mtime. That is
# what lets `switch_mode` re-skin the overlay with no wiring — the render thread simply
# picks up the new accent on the next effect.
_cfg_cache: tuple[float, dict] | None = None
_CFG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "freya_config.json")


def _live_config() -> dict:
    global _cfg_cache
    try:
        mtime = os.path.getmtime(_CFG_PATH)
        if _cfg_cache and _cfg_cache[0] == mtime:
            return _cfg_cache[1]
        import json
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _cfg_cache = (mtime, data)
        return data
    except Exception:
        return {}


def overlay_cfg() -> dict:
    return (_live_config().get("overlay") or {})


def effect_enabled(name: str) -> bool:
    cfg = overlay_cfg()
    if not cfg.get("enabled", True):
        return False
    return bool((cfg.get("effects") or {}).get(name, True))


def _palette() -> tuple[tuple, tuple]:
    """(accent, hot). `palette: "mode"` follows the active persona's theme accent."""
    cfg = _live_config()
    ov = cfg.get("overlay") or {}
    choice = str(ov.get("palette", "mode"))
    if choice != "mode":
        accent = _hex_rgb(choice)
    else:
        mode = cfg.get("active_mode", "default")
        theme = ((cfg.get("modes") or {}).get(mode) or {}).get("theme") or {}
        accent = _hex_rgb(theme.get("accent", "#0f9c6e"))

    # Normalise to full brightness, keeping the hue. A UI accent is chosen to sit
    # calmly behind text — #0f9c6e peaks at 0.61 — and output alpha is derived from
    # luminance, so feeding it in raw caps every line at 61% opacity and the whole
    # overlay reads washed out over a bright desktop. Ink wants to be ink.
    peak = max(accent)
    accent = tuple(min(1.0, c / peak) for c in accent) if peak > 0.01 else (0.1, 1.0, 0.7)

    # Companion tone: lift toward white so highlights read hot, not merely paler.
    hot = tuple(min(1.0, c * 0.35 + 0.68) for c in accent)
    return accent, hot


class ShaderOverlay:
    def __init__(self):
        self._q = queue.Queue()
        self._effects = []
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._ok = False
        self._thread = None
        self._hwnd = None
        self._wndproc_ref = None  # keep the WNDPROC callback alive
        self._shader_files: list[str] = []
        self._shader_mtime = 0.0
        self._last_frame_ms = 0.0

    # ── public ──
    def start(self) -> bool:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=8)
            atexit.register(self.stop)
        return self._ok

    def enqueue(self, kind, rect, param=(0.0, 0.0, 1.0, 1.0)):
        """Queue an effect. Raises nothing, but no longer swallows a type error in
        silence — a bad `kind` is a bug, and one hid here for the life of this file."""
        try:
            k = float(kind)
        except (TypeError, ValueError):
            print(f"  [shader_overlay] bad effect kind {kind!r} — effect dropped")
            return
        try:
            self._q.put((k, tuple(float(v) for v in rect),
                         tuple(float(v) for v in param), time.monotonic()))
        except Exception as e:
            print(f"  [shader_overlay] enqueue failed: {e}")

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.5)

    def frame_ms(self) -> float:
        """Last present-path cost in milliseconds (for the perf check)."""
        return self._last_frame_ms

    # ── render thread ──
    def _run(self):
        try:
            self._init()
            self._ok = True
        except Exception as e:
            print(f"  [shader_overlay] GPU init failed -> tkinter fallback: {e}")
            self._ok = False
            self._ready.set()
            self._teardown()
            return
        self._ready.set()
        try:
            self._loop()
        except Exception as e:
            print(f"  [shader_overlay] render loop error: {e}")
        finally:
            self._teardown()

    def _init(self):
        import moderngl
        import numpy as np
        self._np = np
        _sig()

        user32.SetProcessDPIAware()

        # Span the whole virtual desktop, not just the primary monitor. The origin is
        # negative when a monitor sits left of or above the primary, so every incoming
        # rect is translated by it before reaching the shader.
        self._ox = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        self._oy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        self._w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or user32.GetSystemMetrics(SM_CXSCREEN)
        self._h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or user32.GetSystemMetrics(SM_CYSCREEN)

        # capture_screen() grabs the PRIMARY monitor only, so the scan frame must
        # bracket exactly that region — framing the whole virtual desktop would
        # advertise pixels that were never in the screenshot.
        pw = user32.GetSystemMetrics(SM_CXSCREEN)
        ph = user32.GetSystemMetrics(SM_CYSCREEN)
        self._primary = (float(-self._ox), float(-self._oy),
                         float(-self._ox + pw), float(-self._oy + ph))

        self._wndproc_ref = WNDPROCTYPE(
            lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "FreyaShaderOverlay"
        self._cls = user32.RegisterClassW(ctypes.byref(wc))

        WS_POPUP = 0x80000000
        WS_EX = (0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000)  # LAYERED|TRANSPARENT|TOPMOST|TOOLWINDOW|NOACTIVATE
        self._hwnd = user32.CreateWindowExW(
            WS_EX, "FreyaShaderOverlay", None, WS_POPUP,
            self._ox, self._oy, self._w, self._h, None, None, hinst, None)
        if not self._hwnd:
            raise RuntimeError("CreateWindowEx failed")
        user32.ShowWindow(self._hwnd, 4)  # SW_SHOWNOACTIVATE

        # Bottom-up DIB (positive biHeight) so GL's bottom-up framebuffer maps straight
        # in with no vertical flip on the CPU. The shader already works in top-left
        # coordinates via u_res.y - gl_FragCoord.y, so effect maths is unaffected.
        self._screen_dc = user32.GetDC(0)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self._w
        bmi.bmiHeader.biHeight = self._h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        self._bits = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self._mem_dc, ctypes.byref(bmi), 0, ctypes.byref(self._bits), None, 0)
        if not self._hbmp:
            raise RuntimeError("CreateDIBSection failed")
        gdi32.SelectObject(self._mem_dc, self._hbmp)

        self._ctx = moderngl.create_standalone_context()
        tri = np.array([-1, -1, 3, -1, -1, 3], dtype="f4")
        self._vbo = self._ctx.buffer(tri.tobytes())
        self._tex = self._ctx.texture((self._w, self._h), 4)
        self._fbo = self._ctx.framebuffer(color_attachments=[self._tex])
        self._prog = None
        self._vao = None
        self._load_program()          # raises if the very first compile fails
        self._nbytes = self._w * self._h * 4
        self._buf = bytearray(self._nbytes)     # readback target, allocated once
        self._blank = bytearray(self._nbytes)
        self._t0 = time.monotonic()
        self._present_raw(self._blank)          # start fully transparent

    def _load_program(self):
        """Compile from disk. On failure keep the previous program and report."""
        try:
            vert, frag, files = _shader_sources()
            prog = self._ctx.program(vertex_shader=vert, fragment_shader=frag)
        except Exception as e:
            if self._prog is None:
                raise
            print(f"  [shader_overlay] shader reload failed, keeping previous:\n{e}")
            return
        self._prog = prog
        self._vao = self._ctx.simple_vertex_array(prog, self._vbo, "in_pos")
        self._shader_files = files
        self._shader_mtime = self._newest_mtime()

    def _newest_mtime(self) -> float:
        newest = 0.0
        for f in self._shader_files:
            try:
                newest = max(newest, os.path.getmtime(f))
            except OSError:
                pass
        return newest

    def _set(self, name, value):
        try:
            self._prog[name].value = value
        except KeyError:
            pass          # uniform optimized out — fine
        except Exception as e:
            print(f"  [shader_overlay] uniform '{name}' failed: {e}")

    def _set_arr(self, name, data):
        try:
            self._prog[name].write(data)
        except KeyError:
            pass
        except Exception as e:
            print(f"  [shader_overlay] uniform array '{name}' failed: {e}")

    def _present_raw(self, buf: bytearray):
        # One memmove straight from the readback buffer into the DIB: the shader
        # already produced premultiplied BGRA in this exact row order.
        ctypes.memmove(self._bits, (ctypes.c_char * len(buf)).from_buffer(buf), len(buf))
        pt_dst = WinPoint(self._ox, self._oy)
        siz = SIZE(self._w, self._h)
        pt_src = WinPoint(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, premultiplied AC_SRC_ALPHA
        user32.UpdateLayeredWindow(self._hwnd, self._screen_dc, ctypes.byref(pt_dst),
                                   ctypes.byref(siz), self._mem_dc, ctypes.byref(pt_src),
                                   0, ctypes.byref(blend), 2)  # ULW_ALPHA

    def _loop(self):
        np = self._np
        rects = np.zeros((MAX_FX, 4), "f4")
        params = np.zeros((MAX_FX, 4), "f4")
        starts = np.zeros(MAX_FX, "f4")
        kinds = np.zeros(MAX_FX, "f4")
        cleared = True
        next_reload_check = 0.0

        while not self._stop.is_set():
            while True:
                try:
                    self._effects.append(list(self._q.get_nowait()))
                except queue.Empty:
                    break
            now = time.monotonic()
            self._effects = [e for e in self._effects if (now - e[3]) <= LIFE][-MAX_FX:]

            # Hot reload: edit a .glsl and see it next frame. Checked at 2 Hz so the
            # stat() calls never show up in the frame budget.
            if now > next_reload_check:
                next_reload_check = now + 0.5
                if self._newest_mtime() > self._shader_mtime:
                    print("  [shader_overlay] shaders changed — recompiling")
                    self._load_program()

            cfg = overlay_cfg()
            if self._effects and cfg.get("enabled", True):
                t_frame = time.perf_counter()
                rects[:] = 0.0; starts[:] = 0.0; kinds[:] = 0.0; params[:] = 0.0
                for i, (k, r, p, st) in enumerate(self._effects):
                    rects[i] = r
                    params[i] = p
                    starts[i] = st - self._t0
                    kinds[i] = k
                accent, hot = _palette()
                self._fbo.use()
                self._ctx.clear(0.0, 0.0, 0.0, 0.0)
                self._set("u_res", (float(self._w), float(self._h)))
                self._set("u_time", now - self._t0)
                self._set("u_count", len(self._effects))
                self._set("u_primary", self._primary)
                self._set("u_accent", accent)
                self._set("u_hot", hot)
                self._set("u_intensity", float(cfg.get("intensity", 1.0)))
                self._set_arr("u_rect", rects.tobytes())
                self._set_arr("u_start", starts.tobytes())
                self._set_arr("u_kind", kinds.tobytes())
                self._set_arr("u_param", params.tobytes())
                self._vao.render()
                # Shader already emitted premultiplied BGRA in DIB row order, so this
                # is the only copy between GPU and screen.
                self._fbo.read_into(self._buf, components=4, alignment=1)
                self._present_raw(self._buf)
                self._last_frame_ms = (time.perf_counter() - t_frame) * 1000.0
                cleared = False
            elif not cleared:
                self._present_raw(self._blank)
                cleared = True

            msg = wintypes.MSG()
            while user32.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            fps = float(cfg.get("fps", DEFAULT_FPS)) or DEFAULT_FPS
            time.sleep(1.0 / fps if self._effects else 0.05)

    def _teardown(self):
        try:
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
        except Exception:
            pass
        for obj, fn in ((getattr(self, "_hbmp", None), gdi32.DeleteObject),
                        (getattr(self, "_mem_dc", None), gdi32.DeleteDC)):
            try:
                if obj:
                    fn(obj)
            except Exception:
                pass
        try:
            if getattr(self, "_screen_dc", None):
                user32.ReleaseDC(0, self._screen_dc)
        except Exception:
            pass
        self._hwnd = None

    # ── coordinate helpers ──
    def to_overlay(self, rect):
        """Screen pixels -> overlay-surface pixels (the virtual origin can be negative)."""
        ox, oy = getattr(self, "_ox", 0), getattr(self, "_oy", 0)
        x1, y1, x2, y2 = rect
        return (x1 - ox, y1 - oy, x2 - ox, y2 - oy)


# ── module singleton + public API (mirrors core/overlay.py) ──
_inst = ShaderOverlay()


def start() -> bool:
    return _inst.start()


def stop():
    _inst.stop()


def frame_ms() -> float:
    return _inst.frame_ms()


def _seed() -> float:
    return (time.monotonic() * 997.0) % 1.0


def show_element_effect(rect, label: str = ""):
    if not effect_enabled("element"):
        return
    _inst.enqueue(K_ELEMENT, _inst.to_overlay(rect), (0.0, _seed(), 1.0, 1.0))


def show_click_effect(x, y):
    if not effect_enabled("click"):
        return
    _inst.enqueue(K_CLICK, _inst.to_overlay((x, y, x, y)), (0.0, _seed(), 1.0, 1.0))


def show_move_effect(x, y):
    if not effect_enabled("move"):
        return
    # param.w = 0 -> no chromatic split. This one fires dozens of times per GUI task;
    # sampling the field three times for it would cost real frame budget.
    _inst.enqueue(K_MOVE, _inst.to_overlay((x, y, x, y)), (0.0, _seed(), 0.85, 0.0))


def show_scroll_effect(x, y, direction=None):
    if not effect_enabled("scroll"):
        return
    d = -1.0 if str(direction).lower() in ("up", "-1", "u") else 1.0
    _inst.enqueue(K_SCROLL, _inst.to_overlay((x, y, x, y)), (d, _seed(), 1.0, 1.0))


def show_scan_effect():
    if not effect_enabled("scan"):
        return
    # rect is ignored for SCAN — the shader frames u_primary instead.
    _inst.enqueue(K_SCAN, (0.0, 0.0, 0.0, 0.0), (0.0, _seed(), 1.0, 1.0))


def show_type_effect(x=None, y=None):
    if not effect_enabled("type"):
        return
    if x is None or y is None:
        try:
            pt = WinPoint()
            user32.GetCursorPos(ctypes.byref(pt))
            x, y = pt.x, pt.y
        except Exception:
            x, y = 40, 40
    _inst.enqueue(K_TYPE, _inst.to_overlay((x, y, x, y)), (0.0, _seed(), 1.0, 1.0))
