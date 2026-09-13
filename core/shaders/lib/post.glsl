// ─────────────────────────────────────────────────────────────────────────
//  post.glsl — the "screen" character: chromatic split, scanlines, glitch.
//
//  Note on chromatic aberration: there is no backdrop texture to sample. The
//  overlay draws onto transparency and Windows composites it over the desktop,
//  so we cannot displace pixels we do not own. Instead each effect EVALUATES
//  ITS OWN FIELD three times at slightly offset positions, one per channel.
//  That is what CHROMA3 is for — GLSL 330 has no function pointers, so it has
//  to be a preprocessor macro taking the field function by name.
// ─────────────────────────────────────────────────────────────────────────

// Evaluate a field once per channel along a radial offset. Every effect field
// shares one signature — float f(vec2 px, vec4 rect, float age, float seed) —
// specifically so this macro can stay fixed-arity: variadic macros
// (__VA_ARGS__) are not dependable in GLSL 330 across drivers.
#define CHROMA3(FN, P, OFF, R, AGE, PAR) vec3( \
    FN((P) + (OFF), R, AGE, PAR),              \
    FN((P),         R, AGE, PAR),              \
    FN((P) - (OFF), R, AGE, PAR))

// Radial direction from a centre, safe at the centre itself.
vec2 radialDir(vec2 p, vec2 c) {
    vec2 d = p - c;
    float l = length(d);
    return l < 1e-4 ? vec2(0.0) : d / l;
}

// Horizontal scanlines. `density` is lines per pixel-ish; keep it small.
float scanlines(vec2 px, float density, float depth) {
    return 1.0 - depth * 0.5 * (1.0 + sin(px.y * density * TAU));
}

// A single bright band rolling down the screen, CRT-style.
float rollingBand(float y, float h, float t, float speed, float width) {
    float pos = fract(t * speed) * (h + width * 2.0) - width;
    return exp(-abs(y - pos) / width);
}

// Radial vignette — 0 at the centre, 1 at the corners.
float vignette(vec2 px, vec2 res, float power) {
    vec2 uv = px / res - 0.5;
    return pow(clamp(length(uv) * 1.6, 0.0, 1.0), power);
}

// Blocky UV displacement, retimed in coarse steps so it stutters like dropped
// frames rather than sliding smoothly. `amt` is in pixels.
vec2 glitchOffset(vec2 px, float t, float amt, float blockSize) {
    float row = floor(px.y / blockSize);
    float seed = hash12(vec2(row, qTime(t, 12.0)));
    float active = step(0.82, seed);          // only ~18% of rows displace
    float dir = hash11(seed * 41.7) * 2.0 - 1.0;
    return vec2(dir * amt * active, 0.0);
}

// Tick marks around a rect edge — the "measuring" texture on a HUD frame.
float edgeTicks(vec2 px, vec2 c, vec2 half_, float spacing, float len, float w) {
    vec2 d = abs(px - c) - half_;
    float onTop = step(abs(d.y), w * 2.0) * step(d.x, 0.0);
    float onSide = step(abs(d.x), w * 2.0) * step(d.y, 0.0);
    float fx = step(fract(px.x / spacing), 0.16) * onTop;
    float fy = step(fract(px.y / spacing), 0.16) * onSide;
    float reach = 1.0 - smoothstep(0.0, len, max(abs(d.x), abs(d.y)) + len);
    return max(fx, fy) * clamp(reach + 0.65, 0.0, 1.0);
}
