"use client";

import type { SessionInfo } from "../../hooks/useFreyaSocket";
import { useUptime } from "../../hooks/useUptime";
import HudCard from "./HudCard";

/** Trim the provider prefix/suffix noise so the model reads in a narrow card. */
function shortModel(id: string): string {
  return id.replace(/^models\//, "").replace(/-preview.*$/, "").replace(/-latest$/, "");
}

/**
 * Left column card 3 — the real session: how long it has actually been running,
 * which model is answering, and the active mode.
 *
 * The session id used to be the literal string "FRY-3A7B-9C2D" and the uptime
 * counted from page load with a couple of hours pre-seeded onto it, so both
 * were theatre. Uptime now derives from the backend's session start time and
 * reads "—" when nothing is running.
 */
export default function SessionCard({ session }: { session: SessionInfo | null }) {
  const uptime = useUptime(session?.startedAt);
  const running = !!session?.running;

  return (
    <HudCard title="Active Session">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-3 min-w-0 flex-1">
          <div className="min-w-0">
            <p
              className="text-[9px] tracking-[0.2em] uppercase mb-1"
              style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}
            >
              Model
            </p>
            <p
              className="text-[11px] font-mono tracking-wider truncate"
              style={{ color: "var(--text-primary)" }}
              title={session?.model ?? ""}
            >
              {session?.model ? shortModel(session.model) : "—"}
            </p>
          </div>
          <div>
            <p
              className="text-[9px] tracking-[0.2em] uppercase mb-1"
              style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}
            >
              Uptime
            </p>
            <p
              className="text-[15px] font-mono tracking-widest"
              style={{ color: running ? "var(--accent-red-glow)" : "var(--text-tertiary)" }}
            >
              {uptime ?? "—"}
            </p>
          </div>
        </div>

        {/* Rotating dashed-ring loader — only spins while a session is live. */}
        <svg
          viewBox="0 0 64 64"
          className="w-16 h-16 shrink-0"
          style={{
            animation: running ? "ring-spin 9s linear infinite" : undefined,
            opacity: running ? 1 : 0.35,
            filter: "drop-shadow(0 0 4px var(--accent-red-dim))",
          }}
          aria-hidden
        >
          <circle cx="32" cy="32" r="26" fill="none" stroke="var(--accent-red)" strokeWidth="1.5" strokeDasharray="10 7" opacity="0.85" />
          <circle cx="32" cy="32" r="18" fill="none" stroke="var(--accent-red-dim)" strokeWidth="1" strokeDasharray="4 9" />
        </svg>
      </div>
    </HudCard>
  );
}
