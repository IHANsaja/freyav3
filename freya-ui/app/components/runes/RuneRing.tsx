"use client";

import { FUTHARK } from "./futhark";

interface Props {
  /** 0 = dormant, 1 = listening, 2 = working/speaking — sets glow and speed. */
  charge: 0 | 1 | 2;
  className?: string;
}

/**
 * The 24 runes set in a slowly turning ring, like the circle carved around a
 * galdrastafur. Sits behind the orb in the center stage. Charge brightens it
 * and quickens the turn; at full charge a spark runs rune to rune.
 * Pure SVG + CSS: costs nothing next to the WebGL scene.
 */
export default function RuneRing({ charge, className = "" }: Props) {
  const R = 46;
  return (
    <svg
      aria-hidden
      viewBox="0 0 100 100"
      className={`rune-ring ${className}`}
      data-charge={charge}
      style={{ overflow: "visible" }}
    >
      <circle cx="50" cy="50" r={R + 3.2} className="rune-ring-line" />
      <circle cx="50" cy="50" r={R - 3.4} className="rune-ring-line rune-ring-line--inner" />
      <g className="rune-ring-spin">
        {FUTHARK.map((rune, i) => {
          const a = (i / FUTHARK.length) * 360;
          return (
            <text
              key={rune.name}
              x="50"
              y={50 - R}
              className="rune-ring-glyph"
              transform={`rotate(${a} 50 50)`}
              textAnchor="middle"
              dominantBaseline="central"
              style={{ animationDelay: `${(i * (2.4 / FUTHARK.length)).toFixed(2)}s` }}
            >
              {rune.glyph}
            </text>
          );
        })}
      </g>
    </svg>
  );
}
