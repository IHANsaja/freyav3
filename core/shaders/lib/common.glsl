// ─────────────────────────────────────────────────────────────────────────
//  common.glsl — hashing, noise, SDF primitives and easing.
//
//  Everything here is analytic: no textures are bound, so the whole overlay is
//  one draw call with nothing to upload per frame beyond a handful of uniforms.
//  That matters because the presentation path reads the framebuffer back to the
//  CPU every frame, and a texture upload would land on the same budget.
// ─────────────────────────────────────────────────────────────────────────

const float TAU = 6.28318530718;
const float PI  = 3.14159265359;

// ── Hashing ──────────────────────────────────────────────────────────────
// Integer-free hashes (fract/sin style is banned here — it bands badly on some
// Intel drivers, and this ships to whatever GPU the user happens to have).
float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

vec2 hash22(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xx + p3.yz) * p3.zy);
}

// ── Noise ────────────────────────────────────────────────────────────────
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);               // smoothstep interpolant
    float a = hash12(i);
    float b = hash12(i + vec2(1, 0));
    float c = hash12(i + vec2(0, 1));
    float d = hash12(i + vec2(1, 1));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p, int octaves) {
    float sum = 0.0, amp = 0.5;
    mat2 rot = mat2(0.80, 0.60, -0.60, 0.80);  // rotate each octave so the
    for (int i = 0; i < 6; i++) {              // lattice never lines up
        if (i >= octaves) break;
        sum += amp * vnoise(p);
        p = rot * p * 2.02;
        amp *= 0.5;
    }
    return sum;
}

// Domain warping — fbm displacing its own input. This is what stops an energy
// field reading as "smooth grey blob" and gives it the curdled, turbulent look.
float warpFbm(vec2 p, float amount) {
    vec2 q = vec2(fbm(p, 3), fbm(p + vec2(5.2, 1.3), 3));
    return fbm(p + amount * q, 4);
}

// Voronoi. Returns (distance to nearest cell centre, cell id hash).
vec2 voronoi(vec2 p) {
    vec2 n = floor(p), f = fract(p);
    float best = 8.0, id = 0.0;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 g = vec2(float(i), float(j));
            vec2 o = hash22(n + g);
            float d = length(g + o - f);
            if (d < best) { best = d; id = hash12(n + g); }
        }
    }
    return vec2(best, id);
}

// Hex tiling. Returns (distance to nearest hex EDGE, cell id).
vec2 hexGrid(vec2 p) {
    vec2 s = vec2(1.0, 1.7320508);             // 1, sqrt(3)
    vec2 hC = floor(vec2(p.x / s.x, p.y / s.y)) + 0.5;
    vec2 a = p - vec2(hC.x * s.x, hC.y * s.y);
    vec2 b = p - vec2((hC.x + 0.5) * s.x, (hC.y + 0.5) * s.y);
    vec2 gv = dot(a, a) < dot(b, b) ? a : b;
    vec2 id = dot(a, a) < dot(b, b) ? hC : hC + 0.5;
    vec2 pabs = abs(gv);
    float edge = 0.5 - max(dot(pabs, normalize(vec2(1.0, 1.7320508))), pabs.x);
    return vec2(edge, hash12(id));
}

// ── SDF primitives ───────────────────────────────────────────────────────
float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

float sdBox(vec2 p, vec2 c, vec2 half_) {
    vec2 d = abs(p - c) - half_;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
}

// Distance to the OUTLINE of a rect (not the filled region).
float sdBoxFrame(vec2 p, vec2 c, vec2 half_) {
    return abs(sdBox(p, c, half_));
}

// ── Ink ──────────────────────────────────────────────────────────────────
// A crisp antialiased line of width w from a distance field.
float ln(float d, float w) {
    return 1.0 - smoothstep(0.0, w, d);
}

// Soft exponential falloff — the cheap stand-in for a real separable bloom.
// A true multi-pass blur would need a second FBO and a second readback, and the
// present path is already the frame budget's bottleneck.
float glow(float d, float k) {
    return exp(-d * k);
}

// ── Easing / timing ──────────────────────────────────────────────────────
float easeOutCubic(float t)  { float u = 1.0 - t; return 1.0 - u * u * u; }
float easeOutQuint(float t)  { float u = 1.0 - t; return 1.0 - u * u * u * u * u; }
float easeInOutCubic(float t){ return t < 0.5 ? 4.0*t*t*t : 1.0 - pow(-2.0*t + 2.0, 3.0) / 2.0; }

// Quantise time into n steps per second. Machines don't ease — they step. Used
// for bracket snaps and glitch retiming so the motion reads as digital rather
// than as something organic and alive.
float qTime(float t, float n) { return floor(t * n) / n; }

// Dashed ring mask: 1 inside a dash, 0 in a gap, around angle `ang`.
float dashes(float ang, float count, float duty) {
    float f = fract(ang / TAU * count);
    return step(f, duty);
}

// Convert a linear intensity to premultiplied output alpha. Kept in one place
// so every effect fades out through the same curve.
float inkAlpha(vec3 col) {
    float a = max(col.r, max(col.g, col.b));
    return clamp(max(a - 0.02, 0.0) / 0.98, 0.0, 1.0);
}
