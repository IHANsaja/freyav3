// ─────────────────────────────────────────────────────────────────────────
//  element.glsl — target lock. Fires when Freya resolves a real UI element
//  from UI Automation and is about to act on it.
//
//  The story in ~1.1s: brackets fly in and snap → a reticle spins up and a
//  counter-rotating dashed ring settles → an energy field fills the element →
//  a confirm pulse when lock completes. It should read as deliberate aim, not
//  decoration, because it is the one effect that says "this exact thing".
// ─────────────────────────────────────────────────────────────────────────

float fxElement_field(vec2 px, vec4 R, float age, vec4 par) {
    vec2 c = 0.5 * vec2(R.x + R.z, R.y + R.w);
    vec2 half_ = 0.5 * vec2(abs(R.z - R.x), abs(R.w - R.y));
    float rad = max(half_.x, half_.y);

    float snapT = clamp(age / 0.20, 0.0, 1.0);
    float snap = easeOutQuint(qTime(snapT, 12.0));
    float lockT = smoothstep(0.20, 0.40, age);   // 1 once locked

    float v = 0.0;

    // ── Corner brackets ──
    float mg = mix(26.0, 3.5, snap);
    float arm = mix(7.0, clamp(min(half_.x, half_.y) * 0.55, 12.0, 36.0), snap);
    vec2 h2 = half_ + mg;
    float l = c.x - h2.x, t = c.y - h2.y, r = c.x + h2.x, b = c.y + h2.y;

    float d = 1e9;
    d = min(d, sdSeg(px, vec2(l, t), vec2(l + arm, t)));
    d = min(d, sdSeg(px, vec2(l, t), vec2(l, t + arm)));
    d = min(d, sdSeg(px, vec2(r, t), vec2(r - arm, t)));
    d = min(d, sdSeg(px, vec2(r, t), vec2(r, t + arm)));
    d = min(d, sdSeg(px, vec2(l, b), vec2(l + arm, b)));
    d = min(d, sdSeg(px, vec2(l, b), vec2(l, b - arm)));
    d = min(d, sdSeg(px, vec2(r, b), vec2(r - arm, b)));
    d = min(d, sdSeg(px, vec2(r, b), vec2(r, b - arm)));

    v += ln(d, 2.0) * (0.88 + 0.12 * sin(age * 34.0));
    v += glow(d, 0.10) * 0.18;

    // ── Reticle: solid ring spinning up, dashed ring counter-rotating ──
    vec2 rel = px - c;
    float rl = length(rel);
    float ang = atan(rel.y, rel.x);

    float ringR = mix(rad * 1.55, rad * 1.12, easeOutCubic(clamp(age / 0.34, 0.0, 1.0)));
    float ringD = abs(rl - ringR);
    v += ln(ringD, 1.5) * dashes(ang + age * 2.1, 16.0, 0.55) * 0.75 * lockT;

    float ring2R = ringR + 7.0;
    v += ln(abs(rl - ring2R), 1.1) * dashes(-ang + age * 3.4, 28.0, 0.32) * 0.42 * lockT;

    // Four cardinal aim ticks outside the ring.
    float tick = ln(abs(rl - (ringR + 14.0)), 1.4)
               * step(0.90, abs(cos(ang * 2.0)));
    v += tick * 0.55 * lockT;

    // ── Energy field inside the element ──
    float inside = 1.0 - step(0.0, sdBox(px, c, half_));
    if (inside > 0.5) {
        vec2 q = (px - c) / max(rad, 1.0);
        float field = warpFbm(q * 3.0 + vec2(0.0, -age * 1.6), 1.5);
        // Bias to the border so the element's own content stays readable.
        float border = 1.0 - smoothstep(0.0, 0.42, -sdBox(px, c, half_) / max(rad, 1.0));
        v += field * border * 0.30 * lockT;

        // Vertical data lines sweeping across the element.
        float lanes = step(0.86, fract(q.x * 7.0 - age * 1.1));
        v += lanes * border * 0.12 * lockT;
    }

    // ── Centre crosshair, gapped ──
    float ax = abs(rel.x), ay = abs(rel.y);
    float hx = ln(abs(rel.y), 1.3) * step(5.0, ax) * step(ax, 17.0);
    float hy = ln(abs(rel.x), 1.3) * step(5.0, ay) * step(ay, 17.0);
    v += max(hx, hy) * 0.60;

    // ── Confirm pulse at lock ──
    float pulse = exp(-pow((age - 0.34) * 9.0, 2.0));
    v += ln(abs(rl - (rad + 24.0 + pulse * 26.0)), 2.6) * pulse * 0.9;

    return v;
}
