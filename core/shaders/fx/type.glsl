// ─────────────────────────────────────────────────────────────────────────
//  type.glsl — data entry.
//
//  Previously this mapped to the SCAN kind, so every keystroke burst flashed
//  the full-screen capture frame and read as "she just took a screenshot".
//  It gets its own motif now: a caret and a stream of quantised blocks
//  clocking out to the right, sized and paced like characters landing.
//
//  R is the caret rect (a point at the cursor when no focus rect is known).
// ─────────────────────────────────────────────────────────────────────────

float fxType_field(vec2 px, vec4 R, float age, vec4 par) {
    float seed = par.y;
    vec2 c = 0.5 * vec2(R.x + R.z, R.y + R.w);
    vec2 rel = px - c;

    float life = clamp(age / 0.85, 0.0, 1.0);
    float decay = 1.0 - smoothstep(0.65, 1.0, life);
    float v = 0.0;

    // ── Caret: a vertical bar blinking on a hard digital clock ──
    float blink = step(0.5, fract(qTime(age, 14.0) * 3.4));
    float caret = ln(sdBox(px, c, vec2(1.6, 13.0)), 1.4);
    v += caret * (0.55 + 0.45 * blink) * decay * 1.1;
    v += glow(sdBox(px, c, vec2(1.6, 13.0)), 0.22) * decay * 0.30;

    // ── Character blocks clocking out to the right ──
    // Each block appears on its own tick, then dims — like glyphs committing.
    float cell = 11.0;
    float col = floor(rel.x / cell);
    if (col >= 0.0 && col < 14.0 && abs(rel.y) < 12.0) {
        float appearAt = col * 0.045;
        float t = age - appearAt;
        if (t > 0.0) {
            float bx = (col + 0.5) * cell;
            float h = 3.0 + hash11(col + seed * 7.3) * 8.0;
            float block = 1.0 - step(0.0, sdBox(px, c + vec2(bx, 0.0), vec2(cell * 0.34, h)));
            float settle = exp(-t * 4.2);                  // bright then fades
            v += block * (0.18 + settle * 0.75) * decay;
        }
    }

    // ── Underline track the blocks land on ──
    float track = ln(abs(rel.y - 14.0), 1.1)
                * step(-2.0, rel.x) * step(rel.x, 14.0 * cell);
    v += track * decay * 0.4;

    // ── Data ticks scrolling under the track ──
    float ticks = step(0.78, fract(rel.x * 0.16 - age * 5.0))
                * step(abs(rel.y - 19.0), 2.0)
                * step(-2.0, rel.x) * step(rel.x, 14.0 * cell);
    v += ticks * decay * 0.45;

    return v;
}
