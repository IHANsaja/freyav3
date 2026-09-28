"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../../hooks/useReducedMotion";

/**
 * The rune-cut cursor: a gold point at the exact hotspot, inside a jade
 * diamond — the same cut as Freyja's mark and the dashboard's runes — that
 * trails a touch behind, and a gold ember drifting after it.
 *
 *   hover (anything clickable) → the diamond turns square-on and grows, its
 *                                 corner notches lighting like a rune locking in
 *   press                       → it bites down and a ring pulses outward
 *   text fields                 → the native I-beam returns, so typing still
 *                                 shows where the caret goes
 *
 * Replaces the native cursor only on fine pointers with motion allowed. State
 * lives in data attributes set from the frame loop, so moving the mouse never
 * re-renders React.
 */
const INTERACTIVE = "button, a, [role='button'], [role='tab'], select, summary, label, [tabindex]:not([tabindex='-1'])";
const TEXT = "input:not([type='button']):not([type='submit']):not([type='checkbox']):not([type='radio']):not([type='range']), textarea, [contenteditable='true']";

export default function CustomCursor() {
  const reduced = useReducedMotion();
  const [enabled, setEnabled] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const pointRef = useRef<HTMLDivElement>(null);
  const gemRef = useRef<HTMLDivElement>(null);
  const emberRef = useRef<HTMLDivElement>(null);
  const pulseRef = useRef<HTMLDivElement>(null);

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
    const gem = { x: -100, y: -100 };
    const ember = { x: -100, y: -100 };
    let mode: "idle" | "hover" | "text" = "idle";
    let visible = false;
    let raf = 0;

    const place = (el: HTMLElement | null, x: number, y: number) => {
      if (el) el.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    };

    const onMove = (e: PointerEvent) => {
      pos.x = e.clientX;
      pos.y = e.clientY;
      if (!visible) {
        // First move after entering: start everything at the pointer, no fly-in.
        gem.x = ember.x = pos.x;
        gem.y = ember.y = pos.y;
        visible = true;
        rootRef.current?.setAttribute("data-visible", "1");
      }
      const target = e.target as Element | null;
      const next = target?.closest?.(TEXT) ? "text" : target?.closest?.(INTERACTIVE) ? "hover" : "idle";
      if (next !== mode) {
        mode = next;
        rootRef.current?.setAttribute("data-mode", mode);
      }
    };
    const onLeave = () => {
      visible = false;
      rootRef.current?.removeAttribute("data-visible");
    };
    const onDown = () => {
      rootRef.current?.setAttribute("data-pressed", "1");
      const pulse = pulseRef.current;
      if (pulse) {
        place(pulse, pos.x, pos.y);
        // Restart the ring animation on every press.
        pulse.classList.remove("is-live");
        void pulse.offsetWidth;
        pulse.classList.add("is-live");
      }
    };
    const onUp = () => rootRef.current?.removeAttribute("data-pressed");

    const tick = () => {
      gem.x += (pos.x - gem.x) * 0.32;
      gem.y += (pos.y - gem.y) * 0.32;
      ember.x += (pos.x - ember.x) * 0.1;
      ember.y += (pos.y - ember.y) * 0.1;
      place(pointRef.current, pos.x, pos.y);
      place(gemRef.current, gem.x, gem.y);
      place(emberRef.current, ember.x, ember.y);
      raf = requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("pointerup", onUp, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    raf = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointerup", onUp);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      cancelAnimationFrame(raf);
      document.body.classList.remove("hud-cursor-active");
    };
  }, [enabled]);

  if (!enabled) return null;

  return (
    <div ref={rootRef} aria-hidden className="rune-cursor" data-mode="idle">
      <div ref={emberRef} className="rune-cursor-anchor">
        <span className="rune-cursor-ember" />
      </div>
      <div ref={gemRef} className="rune-cursor-anchor">
        <span className="rune-cursor-gem">
          <i className="n" />
          <i className="e" />
          <i className="s" />
          <i className="w" />
        </span>
      </div>
      <div ref={pulseRef} className="rune-cursor-anchor rune-cursor-pulse-anchor">
        <span className="rune-cursor-pulse" />
      </div>
      <div ref={pointRef} className="rune-cursor-anchor">
        <span className="rune-cursor-point" />
      </div>
    </div>
  );
}
