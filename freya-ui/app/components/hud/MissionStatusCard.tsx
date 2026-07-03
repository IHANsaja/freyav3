"use client";

import { useEffect, useState } from "react";
import type { MissionPayload } from "../../types/events";
import HudCard from "./HudCard";

const CELLS = 20;
const TARGET = 82;

/** Right column card 3 — objective, segmented progress, failure indicator.
 *  A live mission from the socket replaces the simulated archival copy. */
export default function MissionStatusCard({ mission }: { mission?: MissionPayload | null }) {
  const [progress, setProgress] = useState(0);

  // Eased count-up to the target on mount (and whenever the target changes).
  useEffect(() => {
    const start = performance.now();
    const durationMs = 1600;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setProgress(Math.round(eased * TARGET));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const objective = mission?.goal ?? "ARCHIVAL INTEGRITY";
  const filled = Math.round((progress / 100) * CELLS);

  return (
    <HudCard title="Mission Status">
      <div className="flex flex-col gap-3">
        <div>
          <p className="text-[9px] tracking-[0.2em] uppercase mb-1" style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}>
            Objective
          </p>
          <p className="text-[12px] tracking-[0.1em] uppercase truncate" style={{ color: "var(--text-primary)", fontFamily: "var(--font-ui)" }}>
            {objective}
          </p>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-[9px] tracking-[0.2em] uppercase" style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}>
              Progress
            </p>
            <p className="text-[11px] font-mono" style={{ color: "var(--accent-red-glow)" }}>
              {progress}%
            </p>
          </div>
          <div className="flex gap-[3px]" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Mission progress">
            {Array.from({ length: CELLS }, (_, i) => (
              <span
                key={i}
                className="h-2 flex-1 rounded-[1px] transition-colors duration-150"
                style={
                  i < filled
                    ? {
                        background:
                          "linear-gradient(90deg, var(--accent-red-dim), var(--accent-red), var(--accent-red-dim))",
                        backgroundSize: "80px 100%",
                        animation: "progress-glow 2.2s linear infinite",
                        boxShadow: "0 0 4px rgba(255,43,58,0.4)",
                      }
                    : { background: "rgba(255,60,60,0.1)" }
                }
              />
            ))}
          </div>
        </div>

        {/* Failure indicator — slow pulse/flicker, never fully steady */}
        <div
          className="hud-flicker flex items-center justify-center gap-2 border rounded-[6px] py-2 mt-1"
          style={{ borderColor: "rgba(255,43,58,0.4)", background: "rgba(122,15,22,0.18)" }}
          role="alert"
        >
          <span className="w-1.5 h-1.5 rounded-full live-dot" style={{ background: "var(--danger)", boxShadow: "0 0 6px var(--danger)" }} />
          <span className="text-[11px] font-bold tracking-[0.2em]" style={{ fontFamily: "var(--font-ui)", color: "var(--danger)" }}>
            {mission ? (mission.status ?? "ACTIVE").toUpperCase() : "MISSION FAILED"}
          </span>
        </div>
      </div>
    </HudCard>
  );
}
