"use client";

import { FUTHARK, RUNE_SEP } from "./futhark";

interface Props {
  /** "charged" runs a wave of light along the carving (she's working). */
  charged?: boolean;
  className?: string;
  /** Which ætt to start from, so neighbouring bands don't read identically. */
  offset?: number;
  /** Rune count before the pattern repeats (default: the whole futhark). */
  count?: number;
}

/**
 * A carved band of the Elder Futhark — like the inscription running along a
 * runestone's serpent. Decorative (aria-hidden). When `charged`, each rune
 * lights in turn, so the band reads as power flowing through it.
 */
export default function RuneInscription({ charged = false, className = "", offset = 0, count = 24 }: Props) {
  const runes = Array.from({ length: count }, (_, i) => FUTHARK[(i + offset) % FUTHARK.length]);
  return (
    <div
      aria-hidden
      className={`rune-inscription flex items-center justify-center gap-[0.55em] select-none whitespace-nowrap overflow-hidden ${charged ? "is-charged" : ""} ${className}`}
    >
      {runes.map((r, i) => (
        <span key={i} className="rune-inscription-glyph" style={{ animationDelay: `${(i * 0.09).toFixed(2)}s` }}>
          {r.glyph}
          {i % 8 === 7 && i < runes.length - 1 ? <span className="rune-inscription-sep">{RUNE_SEP}</span> : null}
        </span>
      ))}
    </div>
  );
}
