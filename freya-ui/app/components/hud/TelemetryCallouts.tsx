"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import Waveform from "./Waveform";

export interface CalloutEvent {
  seq: number;
  title: string;
  body: string;
}

interface TelemetryCalloutsProps {
  /** Latest externally-injected callout (mode switch, avatar intent). */
  event: CalloutEvent | null;
  /** Current mode id — the ambient SWITCH MODE card echoes it. */
  modeId: string;
}

// Anchor slots around the viewport; connector lines run toward the orb center.
const SLOTS = [
  { style: { top: "12%", left: "3%" }, from: "right" as const },
  { style: { top: "10%", right: "3%" }, from: "left" as const },
  { style: { bottom: "22%", left: "5%" }, from: "right" as const },
  { style: { bottom: "26%", right: "5%" }, from: "left" as const },
];

interface ActiveCallout {
  key: number;
  slot: number;
  title: string;
  body: string;
}

const AMBIENT: ((mode: string) => { title: string; body: string })[] = [
  () => ({ title: "ANIMATE TRANSITION", body: "Transition (flourish) playing." }),
  (mode) => ({ title: "SWITCH MODE", body: `MODE_SWITCHED:${mode}` }),
];

/**
 * Ambient telemetry feed floating over the orb viewport: glass mini-cards
 * that slide in, draw a dotted connector toward the orb, linger, and fade —
 * reappearing at a different anchor. Real events (mode switches, avatar
 * intents) preempt the ambient cycle.
 */
export default function TelemetryCallouts({ event, modeId }: TelemetryCalloutsProps) {
  const reduced = useReducedMotion();
  const [callout, setCallout] = useState<ActiveCallout | null>(null);
  const counter = useRef(0);
  const ambientIdx = useRef(0);
  const lastEventSeq = useRef(0);

  // Ambient cycle: show ~5s, gap ~3–4s.
  useEffect(() => {
    if (reduced) return;
    let show: ReturnType<typeof setTimeout>;
    let hide: ReturnType<typeof setTimeout>;
    const cycle = () => {
      const content = AMBIENT[ambientIdx.current % AMBIENT.length](modeId);
      ambientIdx.current += 1;
      counter.current += 1;
      setCallout({
        key: counter.current,
        slot: Math.floor(Math.random() * SLOTS.length),
        ...content,
      });
      hide = setTimeout(() => {
        setCallout(null);
        show = setTimeout(cycle, 3000 + Math.random() * 1500);
      }, 5000);
    };
    show = setTimeout(cycle, 1500);
    return () => {
      clearTimeout(show);
      clearTimeout(hide);
    };
  }, [reduced, modeId]);

  // External events preempt whatever is showing.
  useEffect(() => {
    if (!event || event.seq === lastEventSeq.current) return;
    lastEventSeq.current = event.seq;
    counter.current += 1;
    setCallout({
      key: counter.current,
      slot: Math.floor(Math.random() * SLOTS.length),
      title: event.title,
      body: event.body,
    });
  }, [event]);

  if (!callout) return null;

  const slot = SLOTS[callout.slot];

  return (
    <div aria-hidden className="absolute inset-0 pointer-events-none overflow-hidden">
      <div
        key={callout.key}
        className="absolute w-56"
        style={{ ...slot.style, animation: "callout-in 0.45s cubic-bezier(0.22,1,0.36,1) both" }}
      >
        {/* Connector: dotted line drawing on toward the orb */}
        <svg
          className="absolute top-1/2 w-24 h-10 overflow-visible"
          style={{
            ...(slot.from === "right" ? { left: "100%" } : { right: "100%", transform: "scaleX(-1)" }),
            // Draw-on: the clip sweeps open from the card toward the orb.
            animation: "connector-draw 0.55s ease-out 0.2s both",
          }}
          viewBox="0 0 96 40"
        >
          <path
            d="M0 4 L56 4 L96 36"
            fill="none"
            stroke="var(--accent-red)"
            strokeWidth="1"
            strokeDasharray="3 4"
            opacity="0.7"
            className="dash-flow"
          />
          <circle cx="96" cy="36" r="2" fill="var(--accent-red)" opacity="0.9" />
        </svg>

        {/* Mini glass card */}
        <div
          className="relative border p-3"
          style={{
            borderColor: "var(--panel-border)",
            background: "var(--panel-bg)",
            backdropFilter: "blur(var(--blur))",
            borderRadius: "var(--radius)",
          }}
        >
          <span className="absolute top-0 left-0 w-2.5 h-2.5 border-t-2 border-l-2" style={{ borderColor: "var(--accent-red)", opacity: 0.6 }} />
          <span className="absolute bottom-0 right-0 w-2.5 h-2.5 border-b-2 border-r-2" style={{ borderColor: "var(--accent-red)", opacity: 0.6 }} />
          <div className="flex items-center gap-2 mb-1.5">
            <svg viewBox="0 0 12 12" className="w-3 h-3" style={{ color: "var(--accent-red)" }} fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden>
              <circle cx="6" cy="6" r="4.5" />
              <circle cx="6" cy="6" r="1.2" fill="currentColor" stroke="none" />
            </svg>
            <p className="text-[9px] font-semibold tracking-[0.2em] uppercase" style={{ fontFamily: "var(--font-ui)", color: "var(--accent-red)" }}>
              {callout.title}
            </p>
          </div>
          <p className="text-[10px] font-mono mb-2" style={{ color: "var(--text-primary)" }}>
            {callout.body}
          </p>
          <Waveform active bars={7} size="sm" />
        </div>
      </div>
    </div>
  );
}
