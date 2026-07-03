"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../../hooks/useReducedMotion";

/**
 * Crosshair/reticle cursor with a lagging particle-dot trail. Replaces the
 * native cursor only on fine pointers with motion allowed; the reticle scales
 * up over interactive elements.
 */
export default function CustomCursor() {
  const reduced = useReducedMotion();
  const [enabled, setEnabled] = useState(false);
  const ringRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const raf = requestAnimationFrame(() =>
      setEnabled(window.matchMedia("(pointer: fine)").matches && !reduced)
    );
    return () => cancelAnimationFrame(raf);
  }, [reduced]);

  useEffect(() => {
    if (!enabled) {
      document.body.classList.remove("hud-cursor-active");
      return;
    }
    document.body.classList.add("hud-cursor-active");

    const pos = { x: -100, y: -100 };
    const ring = { x: -100, y: -100 };
    const dot = { x: -100, y: -100 };
    let overInteractive = false;
    let raf = 0;

    const onMove = (e: PointerEvent) => {
      pos.x = e.clientX;
      pos.y = e.clientY;
      const target = e.target as Element | null;
      overInteractive = !!target?.closest?.("button, a, [role='button'], input, select, textarea");
    };

    const tick = () => {
      // Ring follows tightly; dot trails with heavier lag = the particle.
      ring.x += (pos.x - ring.x) * 0.35;
      ring.y += (pos.y - ring.y) * 0.35;
      dot.x += (pos.x - dot.x) * 0.12;
      dot.y += (pos.y - dot.y) * 0.12;
      if (ringRef.current) {
        const scale = overInteractive ? 1.6 : 1;
        ringRef.current.style.transform = `translate(${ring.x}px, ${ring.y}px) translate(-50%, -50%) scale(${scale})`;
      }
      if (dotRef.current) {
        dotRef.current.style.transform = `translate(${dot.x}px, ${dot.y}px) translate(-50%, -50%)`;
      }
      raf = requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    raf = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
      document.body.classList.remove("hud-cursor-active");
    };
  }, [enabled]);

  if (!enabled) return null;

  return (
    <div aria-hidden className="fixed inset-0 pointer-events-none z-[100]">
      {/* Reticle: ring + crosshair ticks */}
      <div ref={ringRef} className="absolute w-6 h-6 transition-[scale] will-change-transform">
        <div
          className="absolute inset-0 rounded-full border"
          style={{ borderColor: "var(--accent-red-glow)", opacity: 0.8 }}
        />
        <span className="absolute left-1/2 -top-1 w-px h-2 -translate-x-1/2" style={{ background: "var(--accent-red)" }} />
        <span className="absolute left-1/2 -bottom-1 w-px h-2 -translate-x-1/2" style={{ background: "var(--accent-red)" }} />
        <span className="absolute top-1/2 -left-1 h-px w-2 -translate-y-1/2" style={{ background: "var(--accent-red)" }} />
        <span className="absolute top-1/2 -right-1 h-px w-2 -translate-y-1/2" style={{ background: "var(--accent-red)" }} />
      </div>
      {/* Trailing particle */}
      <div
        ref={dotRef}
        className="absolute w-1 h-1 rounded-full will-change-transform"
        style={{ background: "var(--accent-red-glow)", boxShadow: "0 0 6px var(--accent-red-glow)", opacity: 0.7 }}
      />
    </div>
  );
}
