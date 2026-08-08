#version 330

// ─────────────────────────────────────────────────────────────────────────
//  overlay.frag — uniforms, dispatch, palette and compositing.
//
//  One draw call renders every live effect. Each effect contributes a scalar
//  "ink" field, sampled three times along a radial offset so the channels
//  separate (see CHROMA3 in lib/post.glsl), then tinted by the accent colour
//  and accumulated additively.
//
//  MAX_FX and FX_LIFE are #defined by the host loader from the Python
//  constants, so the array sizes and the loop bound can never drift out of
//  sync with them the way the old hardcoded `12` did.
//
//  Output is PREMULTIPLIED BGRA, not RGBA: UpdateLayeredWindow wants BGRA, and
//  swizzling here costs nothing while doing it on the CPU cost a full-frame
//  pass every single frame.
// ─────────────────────────────────────────────────────────────────────────

out vec4 fragColor;

uniform vec2  u_res;         // overlay surface size (virtual desktop)
uniform float u_time;        // seconds since overlay start
uniform int   u_count;       // live effects this frame
uniform vec4  u_primary;     // primary monitor rect in overlay space (scan frame)
uniform vec3  u_accent;      // mode accent, linear-ish sRGB
uniform vec3  u_hot;         // brighter companion tone for highlights
uniform float u_intensity;   // global multiplier from config

uniform vec4  u_rect[MAX_FX];
uniform float u_start[MAX_FX];
uniform float u_kind[MAX_FX];
uniform vec4  u_param[MAX_FX];   // x=direction  y=seed  z=intensity  w=spare

#include "lib/common.glsl"
#include "lib/post.glsl"
#include "fx/scan.glsl"
#include "fx/element.glsl"
#include "fx/click.glsl"
#include "fx/move.glsl"
#include "fx/scroll.glsl"
#include "fx/type.glsl"

// Kind ids — must match the K_* constants in core/shader_overlay.py.
const float K_ELEMENT = 0.0;
const float K_CLICK   = 1.0;
const float K_MOVE    = 2.0;
const float K_SCROLL  = 3.0;
const float K_SCAN    = 4.0;
const float K_TYPE    = 5.0;

void main() {
    // Work in top-left origin pixels; GL hands us bottom-up.
    vec2 px = vec2(gl_FragCoord.x, u_res.y - gl_FragCoord.y);

    vec3 col = vec3(0.0);

    for (int i = 0; i < MAX_FX; i++) {
        if (i >= u_count) break;

        float age = u_time - u_start[i];
        if (age < 0.0 || age > FX_LIFE) continue;

        float k = u_kind[i];
        vec4 R = u_rect[i];
        vec4 par = u_param[i];

        // Envelope: quick in, long tail out. Applied once, here, so no effect
        // has to remember to fade itself.
        float fin  = smoothstep(0.0, 0.05, age);
        float fout = 1.0 - smoothstep(FX_LIFE - 0.38, FX_LIFE, age);
        float env = fin * fout * par.z * u_intensity;
        if (env <= 0.001) continue;

        // Chromatic offset grows with distance from the effect's centre, the
        // way a real lens misbehaves at the edge of its circle. `move` opts out
        // (par.w < 0.5) because it fires constantly and 3x sampling would cost
        // real frame time for an effect nobody studies closely.
        vec2 fxC = 0.5 * vec2(R.x + R.z, R.y + R.w);
        float aberr = par.w * (0.6 + 1.9 * clamp(length(px - fxC) / 420.0, 0.0, 1.0));
        vec2 off = radialDir(px, fxC) * aberr;

        vec3 rgb;
        if (k < 0.5) {
            rgb = CHROMA3(fxElement_field, px, off, R, age, par);
        } else if (k < 1.5) {
            rgb = CHROMA3(fxClick_field, px, off, R, age, par);
        } else if (k < 2.5) {
            float m = fxMove_field(px, R, age, par);     // no split; see above
            rgb = vec3(m);
        } else if (k < 3.5) {
            rgb = CHROMA3(fxScroll_field, px, off, R, age, par);
        } else if (k < 4.5) {
            // Glitch displacement only on the capture effect — it is the one
            // that should feel like the screen itself was sampled.
            vec2 g = glitchOffset(px, age, 5.0 * par.z, 22.0);
            rgb = CHROMA3(fxScan_field, px + g, off, u_primary, age, par);
        } else {
            rgb = CHROMA3(fxType_field, px, off, R, age, par);
        }

        // Tint: the mid channel carries the accent, the split channels push toward
        // the hot tone, so fringes read as light dispersion rather than as three
        // separate coloured copies. The dispersion term is added on top rather
        // than averaged in, so a chromatic edge is BRIGHTER than the line it
        // fringes instead of stealing energy from it.
        vec3 tinted = u_accent * rgb.g * 1.35
                    + u_hot * 0.42 * (rgb.r + rgb.b)
                    + vec3(rgb.r * 0.55, 0.0, rgb.b * 0.55) * 0.30;

        col += tinted * env;
    }

    // Global screen character, scaled by how much ink is actually present so a
    // blank frame stays perfectly transparent.
    float present = clamp(max(col.r, max(col.g, col.b)) * 3.0, 0.0, 1.0);
    if (present > 0.001) {
        col *= scanlines(px, 0.0035, 0.16 * present);
    }

    col = clamp(col, 0.0, 1.0);
    float a = inkAlpha(col);

    // Premultiplied BGRA for UpdateLayeredWindow (ULW_ALPHA).
    fragColor = vec4(col.bgr * a, a);
}
