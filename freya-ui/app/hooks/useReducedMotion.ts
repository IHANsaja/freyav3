"use client";

import { useEffect, useState } from "react";

/** True when the OS asks for reduced motion — decorative HUD animation
 *  (jitter, scramble, cursor, callout cycling) should sit still. */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
