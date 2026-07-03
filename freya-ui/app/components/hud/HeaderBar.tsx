"use client";

import { useRef, useState } from "react";
import { useScramble } from "../../hooks/useScramble";
import type { EngineStatus } from "../../hooks/useEngineStatus";
import Waveform from "./Waveform";

interface HeaderBarProps {
  connected: boolean;
  status: EngineStatus;
  modeLabel: string;
  onOpenSettings: () => void;
}

const DIVIDER = <span aria-hidden className="w-px h-3 self-center" style={{ background: "var(--panel-border)" }} />;

/** Full-width 64px command header: wordmark, live readouts, EQ + settings. */
export default function HeaderBar({ connected, status, modeLabel, onOpenSettings }: HeaderBarProps) {
  const scrambledMode = useScramble(modeLabel.toUpperCase());
  const [fastSpin, setFastSpin] = useState(false);
  const spinTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleGearClick = () => {
    // Snap to a fast spin on click, then settle back to the idle rotation.
    setFastSpin(true);
    if (spinTimer.current) clearTimeout(spinTimer.current);
    spinTimer.current = setTimeout(() => setFastSpin(false), 1200);
    onOpenSettings();
  };

  return (
    <header
      className="h-16 shrink-0 flex items-center justify-between px-5 border-b"
      style={{ borderColor: "var(--panel-border)", background: "rgba(7,5,10,0.6)", backdropFilter: "blur(10px)" }}
    >
      <div className="flex items-center gap-8 min-w-0">
        {/* Wordmark */}
        <div className="shrink-0">
          <h1
            className="text-lg leading-tight tracking-[0.12em]"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--accent-red)",
              textShadow: "0 0 12px rgba(255,43,58,0.55)",
            }}
          >
            F.R.E.Y.A V3.0
          </h1>
          <p className="text-[8px] tracking-[0.3em] uppercase" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-ui)" }}>
            Archival System
          </p>
        </div>

        {/* Live readouts */}
        <div className="hidden md:flex items-center gap-4 text-[10px] font-mono tracking-[0.15em] uppercase" style={{ color: "var(--text-secondary)" }}>
          <div className="flex items-center gap-2">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: connected ? "var(--accent-green)" : "var(--accent-red-dim)",
                boxShadow: connected ? "0 0 8px var(--accent-green)" : "0 0 6px var(--accent-red-dim)",
                animation: "glow-pulse 2.2s ease-in-out infinite",
              }}
            />
            <span style={{ color: connected ? "var(--accent-green)" : "var(--text-tertiary)" }}>
              {connected ? "CONNECTED" : "OFFLINE"}
            </span>
          </div>
          {DIVIDER}
          <div>
            STATUS: <span style={{ color: "var(--accent-red)" }}>{status.statusLabel}</span>
          </div>
          {DIVIDER}
          <div>
            MODE: <span style={{ color: "var(--accent-red)" }}>{scrambledMode}</span>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Waveform active={status.engine === "listening" || status.engine === "processing"} bars={5} />
        <button
          onClick={handleGearClick}
          aria-label="Open system configuration"
          className="w-9 h-9 flex items-center justify-center border transition-colors duration-300 hover:border-[var(--panel-border-hover)]"
          style={{ borderColor: "var(--panel-border)", borderRadius: "6px", color: "var(--text-secondary)" }}
        >
          <svg viewBox="0 0 24 24" className={`w-4 h-4 hud-gear ${fastSpin ? "hud-gear-fast" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden>
            <circle cx="12" cy="12" r="3.2" />
            <path d="M12 2.5v3 M12 18.5v3 M2.5 12h3 M18.5 12h3 M5.3 5.3l2.1 2.1 M16.6 16.6l2.1 2.1 M18.7 5.3l-2.1 2.1 M7.4 16.6l-2.1 2.1" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </header>
  );
}
