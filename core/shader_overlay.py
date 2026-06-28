"""
GPU shader overlay — "Crimson Core Sync".

A transparent, click-through, always-on-top layer that renders real GLSL fragment shaders on
top of the live Windows desktop so you can SEE what Freya is doing as she controls the screen.
The new control engine (core/screen.py) gives us each element's exact bounding rectangle from
UI Automation, so the shader locks a crimson energy field onto the REAL element — fresnel rim
glow + simplex-noise ripple + an expanding scan ring — matching the FreyaCore 3D look.

Transparency approach: we render the shader OFFSCREEN with a moderngl standalone context, then
present it through `UpdateLayeredWindow` with a per-pixel-alpha DIB. This is the only method
that reliably gives true soft-glow transparency over the desktop — color-key and DWM-extend
both fail with OpenGL (they showed an opaque black screen). The window is WS_EX_LAYERED +
WS_EX_TRANSPARENT so it's fully click-through and never blocks Freya's own clicks.

If anything fails to initialize, `start()` returns False and the caller falls back to the
tkinter overlay — this module never hard-crashes Freya. Coordinates are physical screen pixels
(the process is PER_MONITOR_DPI_AWARE via core/vision).
"""

import atexit
import ctypes
from ctypes import wintypes
import queue
import threading
import time

# ── effect kinds / timing ──
ELEMENT, POINT, SCAN = 0.0, 1.0, 2.0
LIFE = 1.1
MAX_FX = 12

# ── Win32 plumbing ──
LRESULT = ctypes.c_ssize_t
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class POINT(ctypes.Structure):
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
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
        wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
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


_VS = """
#version 330
in vec2 in_pos;
void main(){ gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

_FS = """
#version 330
out vec4 fragColor;
uniform vec2  u_res;
uniform float u_time;
uniform int   u_count;
uniform vec4  u_rect[12];
uniform float u_start[12];
uniform float u_kind[12];

vec3 permute(vec3 x){ return mod(((x*34.0)+1.0)*x, 289.0); }
float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                     -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy));
  vec2 x0 = v -   i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0,0.0) : vec2(0.0,1.0);
  vec4 x12 = x0.xyxy + C.xxzz; x12.xy -= i1;
  i = mod(i, 289.0);
  vec3 p = permute( permute( i.y + vec3(0.0, i1.y, 1.0))
                  + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
                          dot(x12.zw,x12.zw)), 0.0);
  m = m*m; m = m*m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}
float sdRoundBox(vec2 p, vec2 b, float r){
  vec2 q = abs(p) - b + r;
  return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}
void main(){
  vec2 px = vec2(gl_FragCoord.x, u_res.y - gl_FragCoord.y);
  vec3 col = vec3(0.0);
  vec3 crimson = vec3(0.83, 0.11, 0.11);
  vec3 hot     = vec3(1.00, 0.55, 0.45);
  for(int i = 0; i < 12; i++){
    if(i >= u_count) break;
    float age = u_time - u_start[i];
    if(age < 0.0 || age > LIFE_C) continue;
    float fade = 1.0 - age / LIFE_C;
    vec4 R = u_rect[i];
    if(u_kind[i] < 1.5){
      vec2 c = 0.5 * vec2(R.x + R.z, R.y + R.w);
      vec2 b = max(0.5 * vec2(abs(R.z - R.x), abs(R.w - R.y)), vec2(3.0));
      vec2 p = px - c;
      float d = sdRoundBox(p, b, min(min(b.x, b.y), 12.0));
      float rim = exp(-abs(d) * 0.05);
      float ringR = age * 130.0;
      float ring = exp(-pow(abs(d - ringR), 2.0) * 0.0007);
      float n = snoise(p * 0.018 + vec2(0.0, u_time * 1.6));
      float energy = rim * (0.55 + 0.45 * n);
      float pulse = 0.55 + 0.45 * sin(age * 20.0 - 1.5);
      float intensity = (energy * 1.25 * pulse + ring * 0.9) * fade;
      col += mix(crimson, hot, clamp(ring * 1.6, 0.0, 1.0)) * intensity;
    } else {
      float yline = age * u_res.y;
      float dl = px.y - yline;
      float line = exp(-dl * dl * 0.0016);
      float n = snoise(vec2(px.x * 0.008, u_time));
      col += crimson * line * fade * (0.65 + 0.35 * n);
    }
  }
  col = clamp(col, 0.0, 1.0);
  float a = max(col.r, max(col.g, col.b));
  a = clamp(max(a - 0.02, 0.0) / 0.98, 0.0, 1.0);
  fragColor = vec4(col * a, a);   // premultiplied for UpdateLayeredWindow
}
""".replace("LIFE_C", f"{LIFE:.4f}")


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

    # ── public ──
    def start(self) -> bool:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=8)
            atexit.register(self.stop)
        return self._ok

    def enqueue(self, kind, rect):
        try:
            self._q.put((float(kind), tuple(float(v) for v in rect), time.monotonic()))
        except Exception:
            pass

    def stop(self):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.5)

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
        self._w = user32.GetSystemMetrics(0)
        self._h = user32.GetSystemMetrics(1)

        # Window class + layered click-through topmost window.
        self._wndproc_ref = WNDPROCTYPE(
            lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = "FreyaCrimsonOverlay"
        self._cls = user32.RegisterClassW(ctypes.byref(wc))

        WS_POPUP = 0x80000000
        WS_EX = (0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000)  # LAYERED|TRANSPARENT|TOPMOST|TOOLWINDOW|NOACTIVATE
        self._hwnd = user32.CreateWindowExW(
            WS_EX, "FreyaCrimsonOverlay", None, WS_POPUP,
            0, 0, self._w, self._h, None, None, hinst, None)
        if not self._hwnd:
            raise RuntimeError("CreateWindowEx failed")
        user32.ShowWindow(self._hwnd, 4)  # SW_SHOWNOACTIVATE

        # DIB section we blit each frame (top-down, 32bpp BGRA premultiplied).
        self._screen_dc = user32.GetDC(0)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self._w
        bmi.bmiHeader.biHeight = -self._h  # negative -> top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        self._bits = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self._mem_dc, ctypes.byref(bmi), 0, ctypes.byref(self._bits), None, 0)
        if not self._hbmp:
            raise RuntimeError("CreateDIBSection failed")
        gdi32.SelectObject(self._mem_dc, self._hbmp)

        # Offscreen GL.
        self._ctx = moderngl.create_standalone_context()
        self._prog = self._ctx.program(vertex_shader=_VS, fragment_shader=_FS)
        tri = np.array([-1, -1, 3, -1, -1, 3], dtype="f4")
        self._vbo = self._ctx.buffer(tri.tobytes())
        self._vao = self._ctx.simple_vertex_array(self._prog, self._vbo, "in_pos")
        self._tex = self._ctx.texture((self._w, self._h), 4)
        self._fbo = self._ctx.framebuffer(color_attachments=[self._tex])
        self._t0 = time.monotonic()
        self._present(np.zeros((self._h, self._w, 4), dtype="u1"))  # start fully transparent

    def _set(self, name, value):
        try:
            self._prog[name].value = value
        except Exception:
            pass

    def _set_arr(self, name, data):
        try:
            self._prog[name].write(data)
        except Exception:
            pass

    def _present(self, bgra):
        ctypes.memmove(self._bits, bgra.ctypes.data, bgra.nbytes)
        pt_dst, siz, pt_src = POINT(0, 0), SIZE(self._w, self._h), POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, premultiplied AC_SRC_ALPHA
        user32.UpdateLayeredWindow(self._hwnd, self._screen_dc, ctypes.byref(pt_dst),
                                   ctypes.byref(siz), self._mem_dc, ctypes.byref(pt_src),
                                   0, ctypes.byref(blend), 2)  # ULW_ALPHA

    def _loop(self):
        np = self._np
        rects = np.zeros((MAX_FX, 4), "f4")
        starts = np.zeros(MAX_FX, "f4")
        kinds = np.zeros(MAX_FX, "f4")
        cleared = True

        while not self._stop.is_set():
            while True:
                try:
                    self._effects.append(list(self._q.get_nowait()))
                except queue.Empty:
                    break
            now = time.monotonic()
            self._effects = [e for e in self._effects if (now - e[2]) <= LIFE][-MAX_FX:]

            if self._effects:
                rects[:] = 0.0; starts[:] = 0.0; kinds[:] = 0.0
                for i, (k, r, st) in enumerate(self._effects):
                    rects[i] = r; starts[i] = st - self._t0; kinds[i] = k
                self._fbo.use()
                self._ctx.clear(0.0, 0.0, 0.0, 0.0)
                self._set("u_res", (float(self._w), float(self._h)))
                self._set("u_time", now - self._t0)
                self._set("u_count", len(self._effects))
                self._set_arr("u_rect", rects.tobytes())
                self._set_arr("u_start", starts.tobytes())
                self._set_arr("u_kind", kinds.tobytes())
                self._vao.render()
                raw = self._fbo.read(components=4, alignment=1)
                arr = np.frombuffer(raw, dtype="u1").reshape(self._h, self._w, 4)[::-1]
                bgra = arr[:, :, [2, 1, 0, 3]].copy()  # RGBA -> BGRA
                self._present(bgra)
                cleared = False
            elif not cleared:
                self._present(np.zeros((self._h, self._w, 4), dtype="u1"))
                cleared = True

            msg = wintypes.MSG()
            while user32.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            time.sleep(1.0 / 45 if self._effects else 0.05)

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


# ── module singleton + public API (mirrors core/overlay.py) ──
_inst = ShaderOverlay()


def start() -> bool:
    return _inst.start()


def stop():
    _inst.stop()


def show_element_effect(rect, label: str = ""):
    _inst.enqueue(ELEMENT, rect)


def show_click_effect(x, y):
    _inst.enqueue(POINT, (x, y, x, y))


def show_move_effect(x, y):
    _inst.enqueue(POINT, (x, y, x, y))


def show_scroll_effect(x, y, direction=None):
    _inst.enqueue(POINT, (x, y, x, y))


def show_scan_effect():
    _inst.enqueue(SCAN, (0, 0, 0, 0))


def show_type_effect():
    _inst.enqueue(SCAN, (0, 0, 0, 0))
