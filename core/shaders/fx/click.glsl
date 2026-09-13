// ─────────────────────────────────────────────────────────────────────────
//  click.glsl — impact. Fires the instant Freya presses the mouse.
//
//  This one had never rendered: POINT was rebound from 1.0 to a ctypes struct
//  in the host module, float(kind) threw, and a bare except swallowed it. So
//  every click Freya has ever made was silent. It gets the loudest short
//  effect of the set to make up for it — but it is over in ~0.5s, because a
//  click is a punctuation mark, not a sentence.
// ─────────────────────────────────────────────────────────────────────────

float fxClick_field(vec2 px, vec4 R, float age, vec4 par) {
    float seed = par.y;
    vec2 c = 0.5 * vec2(R.x + R.z, R.y + R.w);
    vec2 rel = px - c;
    float rl = length(rel);
    float ang = atan(rel.y, rel.x);

    float v = 0.0;
    float life = clamp(age / 0.55, 0.0, 1.0);
    float decay = 1.0 - life;

    // ── Shockwave: fast expanding ring, thinning as it goes ──
    float shockR = easeOutQuint(life) * 150.0;
    float thickness = mix(3.4, 0.9, life);
    float shock = ln(abs(rl - shockR), thickness);
    v += shock * decay * 1.25;

    // Refraction band just inside the wavefront — a compression ripple rather
    // than a second ring, so the impact feels like it displaced something.
    float band = exp(-abs(rl - shockR * 0.86) / 13.0);
    v += band * decay * 0.28 * (0.6 + 0.4 * sin(ang * 9.0 + age * 22.0));

    // ── Radial spokes ──
    float spokes = pow(abs(cos(ang * 6.0 + seed * TAU)), 14.0);
    float spokeReach = smoothstep(shockR * 1.05, shockR * 0.25, rl);
    v += spokes * spokeReach * decay * 0.55;

    // ── Particle burst — hash-seeded so no two clicks look stamped ──
    for (int i = 0; i < 10; i++) {
        float fi = float(i);
        float a = hash11(seed * 31.7 + fi) * TAU;
        float sp = 68.0 + hash11(seed * 17.3 + fi * 2.1) * 92.0;
        float pr = easeOutCubic(life) * sp;
        vec2 pp = c + vec2(cos(a), sin(a)) * pr;
        float dd = length(px - pp);
        v += glow(dd, 0.42) * decay * decay * 0.55;
    }

    // ── Collapsing inner ring — the "commit" tick ──
    float inR = (1.0 - easeOutCubic(clamp(age / 0.24, 0.0, 1.0))) * 26.0;
    v += ln(abs(rl - inR), 1.8) * step(age, 0.24) * 0.95;

    // ── Gapped crosshair at the exact pixel ──
    float ax = abs(rel.x), ay = abs(rel.y);
    float hx = ln(abs(rel.y), 1.4) * step(5.0, ax) * step(ax, 19.0);
    float hy = ln(abs(rel.x), 1.4) * step(5.0, ay) * step(ay, 19.0);
    v += max(hx, hy) * decay * 0.9;

    // Hot core.
    v += glow(rl, 0.16) * decay * 0.35;

    return v;
}
