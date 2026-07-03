"use client";

import { useUptime } from "../../hooks/useUptime";
import HudCard from "./HudCard";

/** Left column card 3 — session identity + live uptime + spinner ring. */
export default function SessionCard() {
  const uptime = useUptime();

  return (
    <HudCard title="Active Session">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-3 min-w-0">
          <div>
            <p className="text-[9px] tracking-[0.2em] uppercase mb-1" style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}>
              Session ID
            </p>
            <p className="text-[12px] font-mono tracking-wider" style={{ color: "var(--text-primary)" }}>
              FRY-3A7B-9C2D
            </p>
          </div>
          <div>
            <p className="text-[9px] tracking-[0.2em] uppercase mb-1" style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}>
              Uptime
            </p>
            <p className="text-[15px] font-mono tracking-widest" style={{ color: "var(--accent-red-glow)" }}>
              {uptime}
            </p>
          </div>
        </div>

        {/* Rotating dashed-ring loader */}
        <svg
          viewBox="0 0 64 64"
          className="w-16 h-16 shrink-0"
          style={{ animation: "ring-spin 9s linear infinite", filter: "drop-shadow(0 0 4px var(--accent-red-dim))" }}
          aria-hidden
        >
          <circle cx="32" cy="32" r="26" fill="none" stroke="var(--accent-red)" strokeWidth="1.5" strokeDasharray="10 7" opacity="0.85" />
          <circle cx="32" cy="32" r="18" fill="none" stroke="var(--accent-red-dim)" strokeWidth="1" strokeDasharray="4 9" />
        </svg>
      </div>
    </HudCard>
  );
}
