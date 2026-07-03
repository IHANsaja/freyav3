"use client";

import { ReactNode } from "react";
import { useJitter } from "../../hooks/useJitter";
import HudCard from "./HudCard";

const ICON_STROKE = { fill: "none", stroke: "currentColor", strokeWidth: 1.25 } as const;

const ICONS: Record<string, ReactNode> = {
  core: <circle cx="8" cy="8" r="5" {...ICON_STROKE} />,
  memory: <path d="M3 5h10v6H3z M5 5V3 M8 5V3 M11 5V3 M5 13v-2 M8 13v-2 M11 13v-2" {...ICON_STROKE} />,
  voice: <path d="M8 3v10 M4 6v4 M12 6v4" {...ICON_STROKE} strokeLinecap="round" />,
  lock: <path d="M4 7h8v6H4z M6 7V5a2 2 0 014 0v2" {...ICON_STROKE} />,
  learn: <path d="M2 12l4-4 3 3 5-6" {...ICON_STROKE} strokeLinecap="round" strokeLinejoin="round" />,
  latency: <path d="M8 3a5 5 0 105 5 M8 8l3-3" {...ICON_STROKE} strokeLinecap="round" />,
};

function Row({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <li className="hud-row flex items-center gap-2.5 px-2 py-1.5 -mx-2 rounded-[4px] group/row">
      <svg viewBox="0 0 16 16" className="w-3.5 h-3.5 shrink-0 transition-all duration-200 group-hover/row:drop-shadow-[0_0_4px_var(--accent-red-glow)]" style={{ color: "var(--accent-red)" }} aria-hidden>
        {icon}
      </svg>
      <span
        className="flex-1 text-[11px] tracking-[0.08em] uppercase"
        style={{ fontFamily: "var(--font-ui)", color: "var(--text-secondary)" }}
      >
        {label}
      </span>
      <span className="text-[11px] font-mono tracking-wider text-right" style={{ color: "var(--accent-green)" }}>
        {value}
      </span>
    </li>
  );
}

/** Left column card 2 — live-jittering system telemetry. */
export default function SystemStatusCard() {
  const memory = useJitter(98, 1, 4200);
  const latency = useJitter(120, 12, 3600);

  return (
    <HudCard
      title="System Status"
      right={
        <svg viewBox="0 0 16 16" className="w-3 h-3" style={{ color: "var(--text-tertiary)" }} aria-hidden>
          <path d="M3 9l3-3 3 3 4-4 M10 5h3v3" {...ICON_STROKE} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      }
    >
      <ul className="flex flex-col gap-0.5">
        <Row icon={ICONS.core} label="Core Systems" value="NOMINAL" />
        <Row icon={ICONS.memory} label="Memory Index" value={`${memory}%`} />
        <Row icon={ICONS.voice} label="Voice Engine" value="ACTIVE" />
        <Row icon={ICONS.lock} label="Security Layer" value="ENCRYPTED" />
        <Row icon={ICONS.learn} label="Adaptive Learning" value="ENABLED" />
        <Row icon={ICONS.latency} label="Response Latency" value={`${latency}ms`} />
      </ul>
    </HudCard>
  );
}
