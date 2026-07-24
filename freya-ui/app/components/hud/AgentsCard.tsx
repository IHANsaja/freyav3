"use client";

import { useEffect, useState } from "react";
import type { AgentJob } from "../../hooks/useFreyaSocket";
import HudCard from "./HudCard";

const S = { fill: "none", stroke: "currentColor", strokeWidth: 1.25, strokeLinecap: "round", strokeLinejoin: "round" } as const;

/** Per-agent glyph so the kind is readable at a glance. */
const KIND_ICON: Record<string, React.ReactNode> = {
  researcher: <path d="M7 11a4 4 0 100-8 4 4 0 000 8z M10 10l3.5 3.5" {...S} />,
  coder: <path d="M6 5L2.5 8 6 11 M10 5l3.5 3 -3.5 3" {...S} />,
  operator: <path d="M3 3h10v8H3z M6.5 13h3 M8 11v2" {...S} />,
  browser: <path d="M8 14A6 6 0 108 2a6 6 0 000 12z M2.4 6.5h11.2 M2.4 9.5h11.2 M8 2c1.8 2 1.8 10 0 12 M8 2C6.2 4 6.2 12 8 14" {...S} />,
  agent: <path d="M8 2v3 M4.5 5.5h7v6h-7z M6.5 8.5h.01 M9.5 8.5h.01" {...S} />,
};

const DONE = new Set(["done", "finished", "complete", "completed"]);

function elapsed(startedAt?: number | null): string {
  if (!startedAt) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function AgentRow({ job }: { job: AgentJob }) {
  const done = DONE.has(job.status.toLowerCase());
  const icon = KIND_ICON[job.kind] ?? KIND_ICON.agent;

  return (
    <li className="hud-row flex flex-col gap-1 px-2 py-2 -mx-2 rounded-[4px] group/row">
      <div className="flex items-center gap-2.5">
        <svg
          viewBox="0 0 16 16"
          className="w-3.5 h-3.5 shrink-0"
          style={{ color: done ? "var(--text-tertiary)" : "var(--accent-red)" }}
          aria-hidden
        >
          {icon}
        </svg>
        <span
          className="text-[11px] tracking-[0.1em] uppercase truncate"
          style={{ fontFamily: "var(--font-ui)", color: "var(--text-primary)" }}
        >
          {job.kind}
        </span>
        <span className="flex-1" />
        {!done && (
          <span
            className="w-1.5 h-1.5 rounded-full live-dot shrink-0"
            style={{ background: "var(--accent-green)", boxShadow: "0 0 6px var(--accent-green)" }}
            aria-hidden
          />
        )}
        <span
          className="text-[10px] font-mono tabular-nums shrink-0"
          style={{ color: done ? "var(--text-tertiary)" : "var(--accent-green)" }}
        >
          {done ? "DONE" : elapsed(job.startedAt)}
        </span>
      </div>

      {/* The task Freya handed it — the thing you actually want to read. */}
      <p
        className="text-[11px] leading-snug line-clamp-2 pl-6"
        style={{ color: "var(--text-secondary)" }}
        title={job.task}
      >
        {job.task || "(no task recorded)"}
      </p>

      {/* Current tool being executed, while it's still working. */}
      {!done && job.step && (
        <p className="text-[10px] font-mono pl-6 truncate" style={{ color: "var(--accent-red-glow)" }}>
          ▸ {job.step}
        </p>
      )}
    </li>
  );
}

/**
 * Live background workers: which sub-agents are running, what task each was
 * given, and which tool it is executing right now.
 *
 * Replaces the old "Core Directives" card, which showed four invented,
 * permanently-static slogans and told you nothing about the system.
 */
export default function AgentsCard({ agents }: { agents: AgentJob[] }) {
  // Re-render once a second so the elapsed timers tick while jobs run.
  const [, setTick] = useState(0);
  const active = agents.filter((a) => !DONE.has(a.status.toLowerCase()));
  useEffect(() => {
    if (active.length === 0) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [active.length]);

  // Running first, then the most recently finished — capped so a long session
  // doesn't grow the card without bound.
  const shown = [...agents]
    .sort((a, b) => Number(DONE.has(a.status.toLowerCase())) - Number(DONE.has(b.status.toLowerCase())))
    .slice(0, 5);

  return (
    <HudCard
      title="Sub-Agents"
      right={
        <span className="text-[10px] font-mono" style={{ color: active.length ? "var(--accent-green)" : "var(--text-tertiary)" }}>
          {active.length} ACTIVE
        </span>
      }
    >
      {shown.length === 0 ? (
        <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
          No background workers running. Ask Freya to research, code or drive the
          browser and they&apos;ll appear here.
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {shown.map((job) => (
            <AgentRow key={job.id} job={job} />
          ))}
        </ul>
      )}
    </HudCard>
  );
}
