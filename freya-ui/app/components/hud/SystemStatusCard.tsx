"use client";

import { ReactNode } from "react";
import type { SessionInfo } from "../../hooks/useFreyaSocket";
import type { EngineStatus } from "../../hooks/useEngineStatus";
import type { HandTrackingStatus } from "../../hooks/useHandGestures";
import HudCard from "./HudCard";

const ICON_STROKE = { fill: "none", stroke: "currentColor", strokeWidth: 1.25 } as const;

const ICONS: Record<string, ReactNode> = {
  core: <circle cx="8" cy="8" r="5" {...ICON_STROKE} />,
  link: <path d="M6.5 9.5a2.5 2.5 0 003.5 0l2-2a2.5 2.5 0 00-3.5-3.5l-.5.5 M9.5 6.5a2.5 2.5 0 00-3.5 0l-2 2a2.5 2.5 0 003.5 3.5l.5-.5" {...ICON_STROKE} strokeLinecap="round" />,
  voice: <path d="M8 3v10 M4 6v4 M12 6v4" {...ICON_STROKE} strokeLinecap="round" />,
  tools: <path d="M10.5 2.5a3 3 0 00-3.9 3.9L3 10l3 3 3.6-3.6a3 3 0 003.9-3.9L11.5 7 9 4.5l1.5-2z" {...ICON_STROKE} strokeLinejoin="round" />,
  mic: <path d="M8 3a1.7 1.7 0 011.7 1.7v3.6a1.7 1.7 0 11-3.4 0V4.7A1.7 1.7 0 018 3z M4.5 8a3.5 3.5 0 007 0 M8 11.5V13" {...ICON_STROKE} strokeLinecap="round" />,
  hand: <path d="M6 9V4.5a1 1 0 012 0V8M8 8V3.6a1 1 0 012 0V8M10 8.2V5a1 1 0 012 0v5c0 2.4-1.8 4.3-4.3 4.3h-.7c-1.8 0-3.4-1.7-3.9-3.1L2.9 8.6c-.2-.6.1-1.2.7-1.4.5-.2 1.1 0 1.4.5l.6 1.3" {...ICON_STROKE} strokeLinecap="round" strokeLinejoin="round" />,
};

type Tone = "ok" | "warn" | "off";

const TONE: Record<Tone, string> = {
  ok: "var(--accent-green)",
  warn: "var(--accent-red-glow)",
  off: "var(--text-tertiary)",
};

function Row({ icon, label, value, tone = "ok" }: { icon: ReactNode; label: string; value: string; tone?: Tone }) {
  return (
    <li className="hud-row flex items-center gap-2.5 px-2 py-1.5 -mx-2 rounded-[4px] group/row">
      <svg
        viewBox="0 0 16 16"
        className="w-3.5 h-3.5 shrink-0 transition-all duration-200 group-hover/row:drop-shadow-[0_0_4px_var(--accent-red-glow)]"
        style={{ color: "var(--accent-red)" }}
        aria-hidden
      >
        {icon}
      </svg>
      <span
        className="flex-1 text-[11px] tracking-[0.08em] uppercase"
        style={{ fontFamily: "var(--font-ui)", color: "var(--text-secondary)" }}
      >
        {label}
      </span>
      <span
        className="text-[11px] font-mono tracking-wider text-right truncate max-w-[52%]"
        style={{ color: TONE[tone] }}
        title={value}
      >
        {value}
      </span>
    </li>
  );
}

const HAND_LABEL: Record<HandTrackingStatus, [string, Tone]> = {
  idle: ["OFF", "off"],
  starting: ["STARTING", "warn"],
  active: ["TRACKING", "ok"],
  denied: ["DENIED", "warn"],
  unsupported: ["N/A", "off"],
  error: ["ERROR", "warn"],
};

/**
 * Left column card 2 — real system telemetry.
 *
 * Every row here used to be invented: a hardcoded "NOMINAL"/"ENCRYPTED"/
 * "ENABLED", plus a random-walk "memory index" and "response latency" that were
 * pure decoration. These now report actual state from the backend and the
 * browser: link status, engine state, the live model/voice, how many tools are
 * registered, whether the mic is paused, and whether the webcam is tracking.
 */
export default function SystemStatusCard({
  session,
  status,
  connected,
  micPaused,
  handTracking,
}: {
  session: SessionInfo | null;
  status: EngineStatus;
  connected: boolean;
  micPaused: boolean;
  handTracking: HandTrackingStatus;
}) {
  const [handValue, handTone] = HAND_LABEL[handTracking];

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
        <Row
          icon={ICONS.link}
          label="Backend Link"
          value={connected ? "ONLINE" : "OFFLINE"}
          tone={connected ? "ok" : "warn"}
        />
        <Row
          icon={ICONS.core}
          label="Engine"
          value={status.statusLabel}
          tone={status.engine === "offline" || status.engine === "stopped" ? "off" : "ok"}
        />
        <Row
          icon={ICONS.voice}
          label="Voice"
          value={session?.voice ?? "—"}
          tone={session?.voice ? "ok" : "off"}
        />
        <Row
          icon={ICONS.tools}
          label="Tools Loaded"
          value={session ? String(session.tools) : "—"}
          tone={session?.tools ? "ok" : "off"}
        />
        <Row
          icon={ICONS.mic}
          label="Microphone"
          value={!status.isRunning ? "IDLE" : micPaused ? "PAUSED" : "LIVE"}
          tone={!status.isRunning ? "off" : micPaused ? "warn" : "ok"}
        />
        <Row icon={ICONS.hand} label="Hand Tracking" value={handValue} tone={handTone} />
      </ul>
    </HudCard>
  );
}
