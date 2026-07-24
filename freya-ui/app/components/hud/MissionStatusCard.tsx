"use client";

import type { MissionPayload, MissionStatus } from "../../types/events";
import HudCard from "./HudCard";

const CELLS = 20;

const DONE_STEPS = new Set(["done", "skipped"]);

/** Status → readout colour. Only genuine failures are red. */
function statusTone(status: MissionStatus | undefined): string {
  if (status === "failed" || status === "cancelled") return "var(--danger)";
  if (status === "done") return "var(--accent-green)";
  return "var(--accent-red-glow)";
}

/**
 * Right column card 3 — real mission progress.
 *
 * This card used to animate a hardcoded count-up to 82% on mount regardless of
 * whether a mission existed, label the objective "ARCHIVAL INTEGRITY", and sit
 * there permanently declaring "MISSION FAILED". Progress is now the mission's
 * actual completed-step ratio, and with no mission running it says so.
 */
export default function MissionStatusCard({ mission }: { mission?: MissionPayload | null }) {
  const steps = mission?.steps ?? [];
  const completed = steps.filter((s) => DONE_STEPS.has(s.status)).length;
  const progress = steps.length ? Math.round((completed / steps.length) * 100) : 0;
  const filled = Math.round((progress / 100) * CELLS);

  const running = steps.find(
    (s) => s.status === "running" || s.status === "verifying" || s.status === "awaiting_approval"
  );

  return (
    <HudCard title="Mission Status">
      {!mission ? (
        <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
          No mission running. Give Freya a big multi-step goal and the plan,
          progress and verification land here.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <div>
            <p
              className="text-[9px] tracking-[0.2em] uppercase mb-1"
              style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}
            >
              Objective
            </p>
            <p
              className="text-[12px] tracking-[0.1em] uppercase line-clamp-2"
              style={{ color: "var(--text-primary)", fontFamily: "var(--font-ui)" }}
              title={mission.goal}
            >
              {mission.goal}
            </p>
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p
                className="text-[9px] tracking-[0.2em] uppercase"
                style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}
              >
                Progress
              </p>
              <p className="text-[11px] font-mono" style={{ color: "var(--accent-red-glow)" }}>
                {completed}/{steps.length} · {progress}%
              </p>
            </div>
            <div
              className="flex gap-[3px]"
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Mission progress"
            >
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
                          boxShadow: "0 0 4px rgba(34,224,160,0.4)",
                        }
                      : { background: "rgba(34,224,160,0.1)" }
                  }
                />
              ))}
            </div>
          </div>

          {/* The step actually executing right now. */}
          {running && (
            <p className="text-[10px] font-mono truncate" style={{ color: "var(--text-secondary)" }} title={running.title}>
              ▸ {running.title}
            </p>
          )}

          <div
            className="flex items-center justify-center gap-2 border rounded-[6px] py-2 mt-1"
            style={{ borderColor: "var(--panel-border)", background: "rgba(10,77,58,0.18)" }}
            role="status"
          >
            <span
              className="w-1.5 h-1.5 rounded-full live-dot"
              style={{ background: statusTone(mission.status), boxShadow: `0 0 6px ${statusTone(mission.status)}` }}
            />
            <span
              className="text-[11px] font-bold tracking-[0.2em]"
              style={{ fontFamily: "var(--font-ui)", color: statusTone(mission.status) }}
            >
              {(mission.status ?? "active").toUpperCase()}
            </span>
          </div>
        </div>
      )}
    </HudCard>
  );
}
