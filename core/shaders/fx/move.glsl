// ─────────────────────────────────────────────────────────────────────────
//  move.glsl — cursor travel.
//
//  Deliberately the cheapest field in the set. A GUI task fires dozens of
//  these in a row, and unlike the others it can overlap itself heavily; a
//  loop-heavy effect here would stack MAX_FX deep and drag the whole overlay's
//  frame time down. No particle loop, no fbm, no chromatic pass (the host
//  gives this one a zero aberration offset).
// ─────────────────────────────────────────────────────────────────────────

float fxMove_field(vec2 px, vec4 R, float age, vec4 par) {
    float seed = par.y;
    vec2 c = 0.5 * vec2(R.x + R.z, R.y + R.w);
    vec2 rel = px - c;
    float rl = length(rel);
    float ang = atan(rel.y, rel.x);

    float life = clamp(age / 0.45, 0.0, 1.0);
    float decay = 1.0 - life;
    float v = 0.0;

    // Soft halo with a shimmer, so it breathes instead of sitting flat.
    float shimmer = 0.82 + 0.18 * sin(ang * 5.0 + age * 15.0 + seed * TAU);
    v += glow(rl, 0.085) * decay * 0.42 * shimmer;

    // Thin ring easing outward.
    float r = 6.0 + easeOutCubic(life) * 17.0;
    v += ln(abs(rl - r), 1.5) * decay * 0.75;

    // Three orbiting ticks — enough to imply tracking, cheap enough to spam.
    float orbit = age * 5.0 + seed * TAU;
    for (int i = 0; i < 3; i++) {
        float a = orbit + float(i) * (TAU / 3.0);
        vec2 pp = c + vec2(cos(a), sin(a)) * (r + 5.0);
        v += glow(length(px - pp), 0.55) * decay * 0.5;
    }

    // Centre dot.
    v += glow(rl, 0.75) * decay;

    return v;
}
