"use client";

import { useEffect, useState } from "react";

/**
 * A number that animates (counts up) into place — used to make figures inside news
 * headlines feel "live" instead of static text.
 */
export default function LiveFigure({
  value,
  suffix = "",
}: {
  value: number;
  suffix?: string;
}) {
  const [n, setN] = useState(0);

  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const dur = 950;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      setN(value * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  const display = Number.isInteger(value)
    ? Math.round(n).toLocaleString()
    : n.toFixed(1);

  return (
    <span className="text-primary font-bold tabular-nums drop-shadow-[0_0_6px_rgba(15,156,110,0.6)]">
      {display}
      {suffix}
    </span>
  );
}
