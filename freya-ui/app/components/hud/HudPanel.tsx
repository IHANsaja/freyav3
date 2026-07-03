"use client";

import { ReactNode } from "react";

interface HudPanelProps {
  title?: string;
  right?: ReactNode;
  notch?: "tl-br" | "tr-bl" | "none";
  scanlines?: boolean;
  brackets?: boolean;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}

/**
 * Foundational HUD surface: a corner-notched, translucent, crimson-bordered
 * panel. The "border" is a stacked color layer clipped by the notch polygon
 * (not a CSS border), so it stays sharp at any size and recolors instantly
 * when persona theming overrides --color-primary-container.
 */
export default function HudPanel({
  title,
  right,
  notch = "tl-br",
  scanlines = true,
  brackets = true,
  className = "",
  bodyClassName = "",
  children,
}: HudPanelProps) {
  const clip = notch === "none" ? "" : notch === "tr-bl" ? "hud-notch-rev" : "hud-notch";

  return (
    <div className={`relative ${className}`}>
      {/* line layer */}
      <div className={`absolute inset-0 ${clip}`} style={{ background: "var(--hud-line)" }} />
      {/* fill layer */}
      <div
        className={`absolute inset-[1px] ${clip}`}
        style={{ background: "var(--hud-fill)", backdropFilter: "blur(6px)" }}
      />
      {scanlines && <div className={`hud-scanlines ${clip}`} />}

      {brackets && notch !== "none" && (
        <>
          <span
            className="absolute w-2.5 h-2.5 pointer-events-none"
            style={{
              [notch === "tr-bl" ? "top" : "bottom"]: -1,
              [notch === "tr-bl" ? "right" : "left"]: -1,
              borderBottom: notch === "tr-bl" ? undefined : "1.5px solid var(--color-primary)",
              borderLeft: notch === "tr-bl" ? undefined : "1.5px solid var(--color-primary)",
              borderTop: notch === "tr-bl" ? "1.5px solid var(--color-primary)" : undefined,
              borderRight: notch === "tr-bl" ? "1.5px solid var(--color-primary)" : undefined,
              opacity: 0.7,
            }}
          />
        </>
      )}

      <div className={`relative flex flex-col ${bodyClassName}`}>
        {title && (
          <div
            className="flex items-center justify-between gap-2 px-4 pt-3 pb-2 text-[10px] font-mono font-bold uppercase tracking-[0.15em] text-primary"
            style={{ borderBottom: "1px solid var(--hud-line)" }}
          >
            <span className="flex items-center gap-1.5">
              <span className="text-[8px] opacity-70">▮</span>
              {title}
            </span>
            {right}
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
