"use client";

import { useEffect, useRef, useState } from "react";

interface TypewriterProps {
  text: string;          // target text (may keep growing as Freya streams)
  className?: string;
  charsPerTick?: number; // how many chars to reveal per frame
  tickMs?: number;       // frame interval
  caret?: boolean;       // show the blinking caret
}

/**
 * Reveals `text` character-by-character. If `text` keeps growing (Freya streaming
 * her words in real time) the loop simply keeps catching up, so it reads like she's
 * typing as she speaks. A single interval converges the shown text toward the latest
 * target read from a ref — no setState during render, no sync setState in an effect.
 */
export default function Typewriter({
  text,
  className = "",
  charsPerTick = 2,
  tickMs = 18,
  caret = true,
}: TypewriterProps) {
  const [shown, setShown] = useState("");
  const targetRef = useRef(text);

  // Keep the latest target in a ref (inside an effect, not during render).
  useEffect(() => {
    targetRef.current = text;
  }, [text]);

  // One ticking loop that converges `shown` toward the current target.
  useEffect(() => {
    const id = setInterval(() => {
      setShown((prev) => {
        const target = targetRef.current;
        if (prev === target) return prev;
        // If the target no longer continues what we've shown, restart from the top.
        if (!target.startsWith(prev)) {
          return target.slice(0, Math.min(charsPerTick, target.length));
        }
        return target.slice(0, Math.min(target.length, prev.length + charsPerTick));
      });
    }, tickMs);
    return () => clearInterval(id);
  }, [charsPerTick, tickMs]);

  return (
    <span className={className}>
      {shown}
      {caret && <span className="type-caret" />}
    </span>
  );
}
