"use client";

import { ReactNode, useState } from "react";

interface HudCardProps {
  title?: string;
  /** Slot rendered on the right side of the title row (icon, chevron…). */
  right?: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Render only the frame (border + brackets), no glass fill — used for the
   *  center orb viewport so the WebGL canvas shows through untinted. */
  frameOnly?: boolean;
  titleColor?: string;
  children?: ReactNode;
}

const BRACKET = "absolute w-3.5 h-3.5 border-[var(--accent-red)] opacity-60 pointer-events-none transition-all duration-300";

/**
 * Signature Archival System panel: glass fill, hairline border, and four
 * L-shaped corner brackets that brighten + extend slightly on hover.
 */
export default function HudCard({
  title,
  right,
  className = "",
  bodyClassName = "",
  frameOnly = false,
  titleColor,
  children,
}: HudCardProps) {
  const [sheen, setSheen] = useState(0);

  return (
    <section
      className={`relative group ${className}`}
      onMouseEnter={() => setSheen((s) => s + 1)}
      style={{ borderRadius: "var(--radius)" }}
    >
      {/* Glass fill + hairline border */}
      <div
        aria-hidden
        className="absolute inset-0 border transition-colors duration-300 group-hover:border-[var(--panel-border-hover)]"
        style={{
          borderRadius: "var(--radius)",
          borderColor: "var(--panel-border)",
          background: frameOnly ? "transparent" : "var(--panel-bg)",
          backdropFilter: frameOnly ? undefined : "blur(var(--blur))",
          WebkitBackdropFilter: frameOnly ? undefined : "blur(var(--blur))",
        }}
      />

      {/* Specular sheen: one diagonal pass per hover (keyed remount restarts it) */}
      {!frameOnly && sheen > 0 && (
        <div aria-hidden className="absolute inset-0 overflow-hidden" style={{ borderRadius: "var(--radius)" }}>
          <div
            key={sheen}
            className="absolute inset-y-0 w-1/3"
            style={{
              background:
                "linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent)",
              animation: "panel-sheen 0.55s ease-out forwards",
            }}
          />
        </div>
      )}

      {/* L-brackets — the four corners, extending outward on hover */}
      <span aria-hidden className={`${BRACKET} top-0 left-0 border-t-2 border-l-2 group-hover:-top-0.5 group-hover:-left-0.5 group-hover:opacity-100`} />
      <span aria-hidden className={`${BRACKET} top-0 right-0 border-t-2 border-r-2 group-hover:-top-0.5 group-hover:-right-0.5 group-hover:opacity-100`} />
      <span aria-hidden className={`${BRACKET} bottom-0 left-0 border-b-2 border-l-2 group-hover:-bottom-0.5 group-hover:-left-0.5 group-hover:opacity-100`} />
      <span aria-hidden className={`${BRACKET} bottom-0 right-0 border-b-2 border-r-2 group-hover:-bottom-0.5 group-hover:-right-0.5 group-hover:opacity-100`} />

      {/* Content */}
      <div className={`relative h-full flex flex-col ${frameOnly ? "" : "p-4"}`}>
        {title && (
          <header className="flex items-center justify-between mb-3">
            <h2
              className="text-[11px] font-semibold uppercase tracking-[0.15em]"
              style={{ fontFamily: "var(--font-ui)", color: titleColor ?? "var(--accent-red)" }}
            >
              {title}
            </h2>
            {right}
          </header>
        )}
        <div className={`flex-1 min-h-0 ${bodyClassName}`}>{children}</div>
      </div>
    </section>
  );
}
