"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "./useReducedMotion";

const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&<>/\\";

/**
 * "Hacker text": whenever `text` changes, the displayed string churns random
 * glyphs and resolves left-to-right over ~600ms. Instant under reduced motion.
 */
export function useScramble(text: string): string {
  const [display, setDisplay] = useState(text);
  const reduced = useReducedMotion();
  const frameRef = useRef(0);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current || reduced) {
      firstRender.current = false;
      // Deferred to a frame so the effect body stays free of sync setState.
      frameRef.current = requestAnimationFrame(() => setDisplay(text));
      return () => cancelAnimationFrame(frameRef.current);
    }

    const durationMs = 600;
    const start = performance.now();

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const resolved = Math.floor(t * text.length);
      let out = text.slice(0, resolved);
      for (let i = resolved; i < text.length; i++) {
        out += text[i] === " " ? " " : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      }
      setDisplay(out);
      if (t < 1) frameRef.current = requestAnimationFrame(tick);
    };

    frameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameRef.current);
  }, [text, reduced]);

  return display;
}
