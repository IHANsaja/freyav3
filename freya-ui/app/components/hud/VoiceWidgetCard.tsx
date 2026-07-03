"use client";

import type { EngineState } from "../../hooks/useEngineStatus";
import HudCard from "./HudCard";
import Waveform from "./Waveform";

const LABELS: Record<EngineState, string> = {
  listening: "LISTENING",
  processing: "SPEAKING",
  paused: "PAUSED",
  stopped: "STANDBY",
  offline: "OFFLINE",
};

/** Right column card 2 — sonar-ring voice widget, pulse keyed to engine state. */
export default function VoiceWidgetCard({ engine }: { engine: EngineState }) {
  const active = engine === "listening" || engine === "processing";
  // Faster pings while she's actually processing speech.
  const period = engine === "processing" ? 1.4 : 2.4;

  return (
    <HudCard
      title="Voice Interaction"
      right={
        <svg viewBox="0 0 16 16" className="w-3 h-3" style={{ color: "var(--text-tertiary)" }} aria-hidden>
          <path d="M8 3v10 M5 6v4 M11 6v4 M2 7.5v1 M14 7.5v1" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
        </svg>
      }
      className="flex-1 min-h-[200px]"
      bodyClassName="flex items-center justify-center py-1"
    >
      <div className="relative w-36 h-36 flex items-center justify-center group/voice">
        {/* Static outer ring */}
        <div aria-hidden className="absolute inset-0 rounded-full border" style={{ borderColor: "var(--panel-border)" }} />
        {/* Sonar pings — staggered, only while the engine is alive */}
        {active &&
          [0, 1, 2].map((i) => (
            <div
              key={i}
              aria-hidden
              className="absolute inset-2 rounded-full border group-hover/voice:opacity-100"
              style={{
                borderColor: "var(--accent-red-glow)",
                animation: `sonar-ping ${period}s ease-out ${(i * period) / 3}s infinite`,
                opacity: 0.8,
              }}
            />
          ))}
        {/* Inner disc */}
        <div
          className="relative w-[6.5rem] h-[6.5rem] rounded-full border flex flex-col items-center justify-center gap-1 transition-shadow duration-300 group-hover/voice:shadow-[0_0_28px_var(--accent-red-dim)]"
          style={{
            borderColor: active ? "var(--accent-red)" : "var(--panel-border)",
            background: "radial-gradient(circle, rgba(122,15,22,0.25) 0%, transparent 70%)",
            boxShadow: active ? "0 0 18px rgba(122,15,22,0.5)" : undefined,
          }}
        >
          <Waveform active={active} bars={5} />
          <p className="text-[13px] font-bold tracking-[0.15em]" style={{ fontFamily: "var(--font-ui)", color: "var(--text-primary)" }}>
            {LABELS[engine]}
          </p>
          <p className="text-[8px] tracking-[0.2em]" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-ui)" }}>
            SPEAK NATURALLY
          </p>
        </div>
      </div>
    </HudCard>
  );
}
