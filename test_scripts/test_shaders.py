"""
Headless GLSL compile check for the desktop overlay.

    venv\\Scripts\\python.exe test_scripts\\test_shaders.py

Builds the program from core/shaders/ in a standalone GL context and fails loudly on a
compile or link error, so a broken #include or a typo in a .glsl file is caught without
needing a desktop session or a visible overlay. Also guards the regression that silently
disabled three effects for the entire life of the module: an effect-kind constant that
was not a number.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import shader_overlay as so

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if not ok and detail else ""))
    if not ok:
        failures.append(label)


def main() -> None:
    # ── 1. every effect kind is a real float ──────────────────────────────
    print("\n[1] effect kind constants")
    kinds = {
        "K_ELEMENT": so.K_ELEMENT, "K_CLICK": so.K_CLICK, "K_MOVE": so.K_MOVE,
        "K_SCROLL": so.K_SCROLL, "K_SCAN": so.K_SCAN, "K_TYPE": so.K_TYPE,
    }
    for name, val in kinds.items():
        try:
            float(val)
            ok = True
        except (TypeError, ValueError):
            ok = False
        check(f"{name} is numeric", ok, f"got {val!r}")
    check("no kind collides with a ctypes struct",
          all(not isinstance(v, type) for v in kinds.values()))
    check("kinds are distinct", len(set(kinds.values())) == len(kinds))

    # ── 2. includes resolve ───────────────────────────────────────────────
    print("\n[2] shader sources")
    try:
        vert, frag, files = so._shader_sources()
        err = ""
    except Exception as e:
        vert = frag = ""
        files = []
        err = str(e)
    check("sources assemble", bool(frag), err)
    check("no unresolved #include left", "#include" not in frag)
    check(f"MAX_FX injected (={so.MAX_FX})", f"#define MAX_FX {so.MAX_FX}" in frag)
    check("FX_LIFE injected", "#define FX_LIFE" in frag)
    check("every fx file was pulled in", len([f for f in files if os.sep + "fx" + os.sep in f]) == 6,
          f"got {[os.path.basename(f) for f in files]}")
    if frag:
        print(f"        assembled fragment shader: {len(frag.splitlines())} lines "
              f"from {len(files)} files")

    # ── 3. it actually compiles ───────────────────────────────────────────
    print("\n[3] GLSL compile + link")
    try:
        import moderngl
        ctx = moderngl.create_standalone_context()
    except Exception as e:
        check("standalone GL context", False, str(e))
        _report()
        return
    check("standalone GL context", True)
    try:
        prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
        check("program compiles and links", True)
    except Exception as e:
        check("program compiles and links", False, str(e)[:4000])
        _report()
        return

    # ── 4. the uniforms the host writes all exist ─────────────────────────
    print("\n[4] uniforms the host writes")
    for name in ("u_res", "u_time", "u_count", "u_primary", "u_accent", "u_hot",
                 "u_intensity", "u_rect", "u_start", "u_kind", "u_param"):
        check(f"{name} present", name in prog, "optimized out or misspelled")

    # ── 5. palette resolution ─────────────────────────────────────────────
    print("\n[5] palette")
    accent, hot = so._palette()
    check("accent is 3 floats in 0..1",
          len(accent) == 3 and all(0.0 <= c <= 1.0 for c in accent), str(accent))
    check("hot is brighter than accent", sum(hot) > sum(accent), f"{accent} -> {hot}")
    print(f"        accent={tuple(round(c, 3) for c in accent)}  hot={tuple(round(c, 3) for c in hot)}")

    # ── 6. each effect actually DRAWS ─────────────────────────────────────
    # Compiling is not the same as rendering. An effect can link fine and put
    # nothing on screen — which is exactly how click/move/scroll stayed invisible
    # for so long. Render one frame per kind offscreen and count lit pixels.
    print("\n[6] each effect renders pixels")
    import numpy as np
    W, H = 640, 400
    tex = ctx.texture((W, H), 4)
    fbo = ctx.framebuffer(color_attachments=[tex])
    tri = np.array([-1, -1, 3, -1, -1, 3], dtype="f4")
    vbo = ctx.buffer(tri.tobytes())
    vao = ctx.simple_vertex_array(prog, vbo, "in_pos")

    def render(kind: float, rect, par, age: float) -> tuple[int, float]:
        rects = np.zeros((so.MAX_FX, 4), "f4")
        pars = np.zeros((so.MAX_FX, 4), "f4")
        starts = np.zeros(so.MAX_FX, "f4")
        kinds = np.zeros(so.MAX_FX, "f4")
        rects[0] = rect
        pars[0] = par
        starts[0] = 0.0
        kinds[0] = kind
        fbo.use()
        ctx.clear(0.0, 0.0, 0.0, 0.0)
        prog["u_res"].value = (float(W), float(H))
        prog["u_time"].value = age
        prog["u_count"].value = 1
        prog["u_primary"].value = (0.0, 0.0, float(W), float(H))
        prog["u_accent"].value = accent
        prog["u_hot"].value = hot
        prog["u_intensity"].value = 1.0
        prog["u_rect"].write(rects.tobytes())
        prog["u_start"].write(starts.tobytes())
        prog["u_kind"].write(kinds.tobytes())
        prog["u_param"].write(pars.tobytes())
        vao.render()
        buf = np.frombuffer(fbo.read(components=4, alignment=1), dtype="u1")
        buf = buf.reshape(H, W, 4)
        alpha = buf[:, :, 3]
        return int((alpha > 4).sum()), float(alpha.max()) / 255.0

    cx, cy = W * 0.5, H * 0.5
    cases = [
        ("element", so.K_ELEMENT, (cx - 90, cy - 30, cx + 90, cy + 30), (0.0, 0.4, 1.0, 1.0)),
        ("click",   so.K_CLICK,   (cx, cy, cx, cy),                     (0.0, 0.4, 1.0, 1.0)),
        ("move",    so.K_MOVE,    (cx, cy, cx, cy),                     (0.0, 0.4, 0.85, 0.0)),
        ("scroll",  so.K_SCROLL,  (cx, cy, cx, cy),                     (1.0, 0.4, 1.0, 1.0)),
        ("scan",    so.K_SCAN,    (0.0, 0.0, 0.0, 0.0),                 (0.0, 0.4, 1.0, 1.0)),
        ("type",    so.K_TYPE,    (cx - 60, cy, cx - 60, cy),           (0.0, 0.4, 1.0, 1.0)),
    ]
    for name, kind, rect, par in cases:
        # Sample a few ages — some effects peak early, some late.
        best_lit, best_a = 0, 0.0
        for age in (0.06, 0.25, 0.5, 0.8):
            lit, amax = render(kind, rect, par, age)
            best_lit, best_a = max(best_lit, lit), max(best_a, amax)
        check(f"{name} draws pixels", best_lit > 200,
              f"only {best_lit} lit px, peak alpha {best_a:.2f}")
        print(f"        {name:<8} peak {best_lit:>7,} lit px, max alpha {best_a:.2f}")

    # A frame with no effects must be perfectly transparent, or the overlay would
    # sit as a grey sheet over the desktop.
    fbo.use()
    ctx.clear(0.0, 0.0, 0.0, 0.0)
    prog["u_count"].value = 0
    vao.render()
    empty = np.frombuffer(fbo.read(components=4, alignment=1), dtype="u1")
    check("empty frame is fully transparent", int(empty.max()) == 0, f"max byte {int(empty.max())}")

    # Effects must expire: past FX_LIFE nothing should be drawn.
    lit_dead, _ = render(so.K_CLICK, (cx, cy, cx, cy), (0.0, 0.4, 1.0, 1.0), so.LIFE + 0.2)
    check("expired effect draws nothing", lit_dead == 0, f"{lit_dead} lit px after LIFE")

    _report()


def _report():
    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} FAILURE(S): " + ", ".join(failures))
        sys.exit(1)
    print("All shader checks passed.")


if __name__ == "__main__":
    main()
