"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RuneAwakening } from "./runeAwakening";
import { useReducedMotion } from "../../hooks/useReducedMotion";

/**
 * The opening: Mímir's well awakens (see runeAwakening.ts for the scene).
 *
 * Plays every time the dashboard is opened (?intro=0 skips it for a quick
 * reload); any key, click or the Skip button ends it. It is built to never stand
 * between the user and the dashboard:
 *   • the TSL scene loads client-side only, behind a dynamic import;
 *   • no WebGPU and no WebGL 2 → a CSS-only version of the same beats;
 *   • any error at all → the intro simply ends;
 *   • a hard 12 s ceiling, whatever happens;
 *   • reduced motion → a short still version.
 */

const HARD_LIMIT_MS = 12_000;

// Mirrors runeAwakening.TIMELINE — kept here so the captions don't need the
// three.js chunk to load first (the fallback runs without it).
const T = { runes: 1.0, well: 2.4, tree: 3.4, seidr: 4.5, title: 5.0, fadeOut: 6.6, end: 7.4 };

const CAPTIONS: { at: number; rune: string; text: string }[] = [
  { at: T.runes, rune: "ᚠ", text: "The Elder Futhark wakes" },
  { at: T.well, rune: "ᛟ", text: "Mímir’s well stirs beneath the roots" },
  { at: T.tree, rune: "ᛇ", text: "Yggdrasil’s branches carry the signal" },
  { at: T.seidr, rune: "ᚨ", text: "Seiðr and circuitry, bound as one" },
];

// Each letter of her name, with the rune it resolves from.
const NAME: [string, string][] = [["F", "ᚠ"], ["R", "ᚱ"], ["E", "ᛖ"], ["Y", "ᛃ"], ["J", "ᛃ"], ["A", "ᚨ"]];

function shouldPlay(): boolean {
  try {
    return new URLSearchParams(window.location.search).get("intro") !== "0";
  } catch {
    return true;
  }
}

/** `?intro=4.5` starts the sequence 4.5 s in — for tuning a single beat. */
function startOffset(): number {
  try {
    const v = parseFloat(new URLSearchParams(window.location.search).get("intro") ?? "");
    return Number.isFinite(v) && v > 0 ? v : 0;
  } catch {
    return 0;
  }
}

export default function IntroSequence({ onDone }: { onDone: () => void }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<RuneAwakening | null>(null);
  const doneRef = useRef(false);
  const [t, setT] = useState(0);            // coarse clock for captions (10 Hz)
  const [mode, setMode] = useState<"loading" | "tsl" | "css">("loading");
  const reducedMotion = useReducedMotion();
  const [leaving, setLeaving] = useState(false);

  const finish = useCallback(() => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    setTimeout(onDone, 450);               // let the fade play
  }, [onDone]);

  // ── Decide, then build the scene (or a fallback) ──
  useEffect(() => {
    if (!shouldPlay()) {
      doneRef.current = true;
      onDone();
      return;
    }
    let cancelled = false;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // The intro's clock counts only frames actually shown: requestAnimationFrame
    // pauses in a background tab, so opening the dashboard behind another tab
    // no longer "plays" the intro to nobody. The ceiling is on that same clock,
    // plus a generous wall-clock backstop in case frames never come at all.
    const ceiling = reduced ? 2.6 : HARD_LIMIT_MS / 1000;
    const backstop = setTimeout(finish, 60_000);

    let shown = startOffset();
    let last = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      shown += Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      if (shown >= ceiling) {
        finish();
        return;
      }
      const seconds = sceneRef.current ? sceneRef.current.elapsed() : shown;
      setT((prev) => (Math.abs(prev - seconds) >= 0.1 ? Math.round(seconds * 10) / 10 : prev));
      if (seconds >= T.end) finish();
      else raf = requestAnimationFrame(tick);
    };

    if (!reduced) {
      (async () => {
        try {
          const { createRuneAwakening } = await import("./runeAwakening");
          if (cancelled || !hostRef.current) return;
          const scene = await createRuneAwakening(hostRef.current);
          if (cancelled) {
            scene.dispose();
            return;
          }
          // The CSS layer has been telling the story while the GPU warmed up;
          // pick up from the same moment rather than starting over.
          scene.seek(shown);
          sceneRef.current = scene;
          setMode("tsl");
          console.info(`[intro] rune awakening on ${scene.backend}`);
        } catch (e) {
          // No WebGPU and no WebGL 2, a shader that won't compile, a chunk
          // that failed to load — the CSS version tells the same story.
          console.warn("[intro] 3D scene unavailable, using the CSS version:", e);
          if (!cancelled) setMode("css");
        }
      })();
    }
    raf = requestAnimationFrame((now) => {
      last = now;
      tick(now);
    });

    return () => {
      cancelled = true;
      clearTimeout(backstop);
      cancelAnimationFrame(raf);
      sceneRef.current?.dispose();
      sceneRef.current = null;
    };
  }, [finish, onDone]);

  // ── Skip: any key, any click ──
  useEffect(() => {
    const skip = () => finish();
    window.addEventListener("keydown", skip);
    return () => window.removeEventListener("keydown", skip);
  }, [finish]);

  const still = reducedMotion;
  const caption = [...CAPTIONS].reverse().find((c) => t >= c.at);
  const showTitle = still || t >= T.title;
  const fading = leaving || t >= T.fadeOut;

  return (
    <div
      role="dialog"
      aria-label="Freyja is waking up. Press any key to skip."
      className={`intro-root ${fading ? "is-leaving" : ""}`}
      onPointerDown={finish}
    >
      {/* The TSL canvas mounts here. */}
      <div ref={hostRef} className="absolute inset-0" aria-hidden />

      {/* CSS rendition: same beats, no GPU needed. */}
      {(mode !== "tsl" || still) && (
        <div aria-hidden className={`intro-css ${mode === "loading" ? "is-loading" : ""}`}>
          <div className="intro-css-ring">
            {"ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ".split("").map((g, i) => (
              <span
                key={i}
                style={{
                  transform: `rotate(${(i / 24) * 360}deg) translateY(calc(-1 * var(--ring-r))) rotate(${-(i / 24) * 360}deg)`,
                  animationDelay: still ? "0s" : `${T.runes + i * 0.1}s`,
                }}
              >
                {g}
              </span>
            ))}
          </div>
          <div className="intro-css-core" style={{ animationDelay: still ? "0s" : `${T.seidr}s` }} />
        </div>
      )}

      {/* Captions */}
      <div className="intro-captions">
        {caption && !showTitle && (
          <p key={caption.text} className="intro-caption">
            <span className="intro-caption-rune" aria-hidden>{caption.rune}</span>
            {caption.text}
          </p>
        )}
      </div>

      {/* Her name, resolving out of her runes */}
      {showTitle && (
        <div className="intro-titlebox">
          <h1 className="intro-title" aria-label="Freyja">
            {NAME.map(([latin, rune], i) => (
              <span key={i} className="intro-letter" style={{ animationDelay: still ? "0s" : `${i * 0.11}s` }}>
                <span className="intro-letter-rune" aria-hidden>{rune}</span>
                <span className="intro-letter-latin" aria-hidden>{latin}</span>
              </span>
            ))}
          </h1>
          <p className="intro-subtitle">Norse-forged ᛫ neural-born</p>
        </div>
      )}

      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={finish}
        className="intro-skip"
      >
        Skip <span aria-hidden>᛫</span> any key
      </button>
    </div>
  );
}
