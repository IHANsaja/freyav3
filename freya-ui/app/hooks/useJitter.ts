"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "./useReducedMotion";

/**
 * Telemetric micro-jitter: nudges a base value by ±range every few seconds so
 * readouts feel live. Settles back toward the base (never random-walks away).
 */
export function useJitter(base: number, range: number, intervalMs = 4000): number {
  const [value, setValue] = useState(base);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) {
      const raf = requestAnimationFrame(() => setValue(base));
      return () => cancelAnimationFrame(raf);
    }
    const id = setInterval(() => {
      // Bias toward base: 40% of ticks settle exactly on it.
      const settle = Math.random() < 0.4;
      const offset = settle ? 0 : Math.round((Math.random() * 2 - 1) * range);
      setValue(base + offset);
    }, intervalMs + Math.random() * 1500);
    return () => clearInterval(id);
  }, [base, range, intervalMs, reduced]);

  return value;
}
