"use client";

import { ReactNode } from "react";
import HudCard from "./HudCard";

const S = { fill: "none", stroke: "currentColor", strokeWidth: 1.25, strokeLinecap: "round", strokeLinejoin: "round" } as const;

const DIRECTIVES: { label: string; icon: ReactNode }[] = [
  {
    label: "Preserve Knowledge",
    icon: <path d="M8 2l5 2v4c0 3.5-2 5.5-5 6.5C5 13.5 3 11.5 3 8V4l5-2z" {...S} />,
  },
  {
    label: "Ensure Continuity",
    icon: <path d="M13 8a5 5 0 11-1.5-3.5 M13 2.5V5h-2.5" {...S} />,
  },
  {
    label: "Protect Assets",
    icon: <path d="M4 7h8v6H4z M6 7V5a2 2 0 014 0v2 M8 9.5v1.5" {...S} />,
  },
  {
    label: "Adapt & Respond",
    icon: <path d="M3 4h5l2 8h3 M11 10l2 2-2 2 M3 12h3" {...S} />,
  },
];

/** Right column card 1 — the four standing directives. */
export default function CoreDirectivesCard() {
  return (
    <HudCard
      title="Core Directives"
      right={
        <svg viewBox="0 0 16 16" className="w-3 h-3 hud-gear" style={{ color: "var(--text-tertiary)" }} aria-hidden>
          <circle cx="8" cy="8" r="2.2" {...S} />
          <path d="M8 2v2 M8 12v2 M2 8h2 M12 8h2 M3.8 3.8l1.4 1.4 M10.8 10.8l1.4 1.4 M12.2 3.8l-1.4 1.4 M5.2 10.8l-1.4 1.4" {...S} />
        </svg>
      }
    >
      <ul className="flex flex-col gap-1">
        {DIRECTIVES.map(({ label, icon }) => (
          <li key={label} className="hud-row flex items-center gap-3 px-2 py-2 -mx-2 rounded-[4px] group/row">
            <span
              className="w-6 h-6 shrink-0 flex items-center justify-center border rounded-[4px] transition-all duration-200 group-hover/row:shadow-[0_0_8px_var(--accent-red-dim)]"
              style={{ borderColor: "var(--panel-border)" }}
            >
              <svg viewBox="0 0 16 16" className="w-3.5 h-3.5" style={{ color: "var(--accent-red)" }} aria-hidden>
                {icon}
              </svg>
            </span>
            <span className="text-[11px] tracking-[0.1em] uppercase" style={{ fontFamily: "var(--font-ui)", color: "var(--text-secondary)" }}>
              {label}
            </span>
          </li>
        ))}
      </ul>
    </HudCard>
  );
}
