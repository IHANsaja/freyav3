// ─────────────────────────────────────────────────────────────────────────
//  scroll.glsl — directional flow.
//
//  par.x carries the direction (+1 down, -1 up), which the previous host code
//  accepted and then threw away, so scrolling either way looked identical.
//  Everything here is mirrored through it so up and down read differently at a
//  glance.
// ─────────────────────────────────────────────────────────────────────────

float fxScroll_field(vec2 px, vec4 R, float age, vec4 par) {
    vec2 c = 0.5 * vec2(R.x + R.z, R.y + R.w);
    float dir = par.x >= 0.0 ? 1.0 : -1.0;
    float seed = par.y;

    vec2 rel = px - c;
    float life = clamp(age / 0.60, 0.0, 1.0);
    float decay = 1.0 - life;
    float v = 0.0;

    // Narrow vertical channel, so this reads as a gesture at the cursor rather
    // than a full-screen wipe.
    float halfW = 34.0;
    float inChannel = 1.0 - smoothstep(halfW * 0.6, halfW, abs(rel.x));
    if (inChannel < 0.002) return 0.0;

    // Chevrons streaming along the axis.
    float travel = age * 210.0;
    for (int i = 0; i < 4; i++) {
        float fi = float(i);
        float y = rel.y * dir + travel - fi * 26.0;
        float wrapped = mod(y, 104.0) - 52.0;
        float chev = abs(wrapped) + abs(rel.x) * 0.55;   // two mirrored arms
        v += ln(abs(chev - 12.0), 2.2) * exp(-fi * 0.45) * inChannel * decay * 0.9;
    }

    // Motion-blur streaks smeared along the travel axis.
    float streak = step(0.72, hash11(floor(rel.x / 5.0) + seed * 13.0));
    v += streak * exp(-abs(rel.y) / 90.0) * inChannel * decay * 0.22;

    // Bright cap at the leading edge of the motion.
    float capY = dir * 62.0 * easeOutCubic(life);
    v += ln(abs(rel.y - capY), 2.4) * inChannel * decay * 0.85;

    // Axis guide.
    v += ln(abs(rel.x), 1.2) * exp(-abs(rel.y) / 70.0) * decay * 0.35;

    return v;
}
