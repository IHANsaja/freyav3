// ─────────────────────────────────────────────────────────────────────────
//  scan.glsl — the screenshot effect. "A sensor just read this screen."
//
//  Deliberately PERIMETER-WEIGHTED. This fires while the user is working, and
//  once per interval for the whole duration of an ambient watch, so the middle
//  of the screen has to stay readable. Everything expensive-looking is pushed
//  to the edges; the centre gets only a fast sweep line and a brief flash.
//
//  Framed on u_primary, not the full virtual desktop: capture_screen() grabs
//  the primary monitor only, so bracketing anything else would advertise a
//  region that was never in the image.
// ─────────────────────────────────────────────────────────────────────────

float fxScan_field(vec2 px, vec4 R, float age, vec4 par) {
    float L = R.x, T = R.y, Rr = R.z, B = R.w;
    float w = Rr - L, h = B - T;

    // Brackets snap inward in coarse steps — machine, not spring.
    float snapT = clamp(age / 0.22, 0.0, 1.0);
    float snap = easeOutQuint(qTime(snapT, 14.0));
    float m = mix(78.0, 24.0, snap);
    float arm = mix(30.0, 104.0, snap);

    float l = L + m, t = T + m, r = Rr - m, b = B - m;

    float d = 1e9;
    d = min(d, sdSeg(px, vec2(l, t), vec2(l + arm, t)));
    d = min(d, sdSeg(px, vec2(l, t), vec2(l, t + arm)));
    d = min(d, sdSeg(px, vec2(r, t), vec2(r - arm, t)));
    d = min(d, sdSeg(px, vec2(r, t), vec2(r, t + arm)));
    d = min(d, sdSeg(px, vec2(l, b), vec2(l + arm, b)));
    d = min(d, sdSeg(px, vec2(l, b), vec2(l, b - arm)));
    d = min(d, sdSeg(px, vec2(r, b), vec2(r - arm, b)));
    d = min(d, sdSeg(px, vec2(r, b), vec2(r, b - arm)));

    float v = ln(d, 2.2) * (0.9 + 0.1 * sin(age * 40.0));
    v += glow(d, 0.045) * 0.16;

    // Hairline frame joining the corners, drawn on after the brackets land.
    vec2 c = vec2(0.5 * (l + r), 0.5 * (t + b));
    vec2 hf = vec2(0.5 * (r - l), 0.5 * (b - t));
    v += ln(sdBoxFrame(px, c, hf), 1.3) * 0.34 * snap;

    // Measuring ticks along the frame.
    v += edgeTicks(px, c, hf, 46.0, 10.0, 1.1) * 0.45 * snap;

    // Hex lattice, revealed near the edges only and dissolved by fbm so it
    // looks like a sensor grid resolving rather than a flat texture.
    float edgeAmt = 1.0 - smoothstep(0.0, 0.34, sdBox(px, c, hf) / max(w, h) + 0.34);
    if (edgeAmt > 0.001) {
        vec2 hx = hexGrid(px / 26.0);
        float lattice = ln(hx.x, 0.055);
        float dissolve = step(hash11(hx.y * 91.7), clamp(age * 2.4, 0.0, 1.0) * 0.55);
        float breathe = 0.55 + 0.45 * sin(age * 9.0 + hx.y * TAU);
        v += lattice * dissolve * breathe * edgeAmt * 0.30;
    }

    // The sweep. One pass down the frame, fast, with a bright leading edge and
    // a short trailing smear — this is the part that reads as "scanning".
    float sp = age / 0.55;
    if (sp < 1.0 && px.x > l && px.x < r) {
        float ys = mix(t, b, easeInOutCubic(sp));
        float dy = px.y - ys;
        v += ln(abs(dy), 2.0) * 1.15 * (1.0 - sp);                 // leading edge
        v += exp(-max(-dy, 0.0) * 0.035) * step(dy, 0.0) * 0.16 * (1.0 - sp);  // trail
        // Noise crackle riding the sweep line.
        v += ln(abs(dy), 9.0) * warpFbm(vec2(px.x * 0.02, age * 6.0), 1.2) * 0.35 * (1.0 - sp);
    }

    // Rolling CRT band, low amplitude, edge-biased.
    v += rollingBand(px.y, B - T, age, 0.85, 46.0) * 0.05 * edgeAmt;

    // Shutter flash: whole frame brightens for ~120ms at capture.
    v += (1.0 - smoothstep(0.0, 0.13, age)) * 0.055 * (0.35 + 0.65 * vignette(px, vec2(Rr, B), 1.4));

    return v;
}
