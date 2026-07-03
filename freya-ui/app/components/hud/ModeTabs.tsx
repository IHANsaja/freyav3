"use client";

import { MouseEvent, useRef, useState } from "react";

interface ModeTabsProps {
  modes: Record<string, { label: string }>;
  activeMode: string;
  connected: boolean;
  onSelect: (id: string) => void;
}

/** Pill-shaped mode selector. Active pill breathes; clicks ripple from the
 *  cursor point. Pills stay visible offline but no-op with a shake. */
export default function ModeTabs({ modes, activeMode, connected, onSelect }: ModeTabsProps) {
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number; key: string }[]>([]);
  const [shake, setShake] = useState<string | null>(null);
  const rippleId = useRef(0);

  const handleClick = (e: MouseEvent<HTMLButtonElement>, id: string) => {
    const rect = e.currentTarget.getBoundingClientRect();
    rippleId.current += 1;
    const ripple = { id: rippleId.current, x: e.clientX - rect.left, y: e.clientY - rect.top, key: id };
    setRipples((r) => [...r.slice(-3), ripple]);
    if (!connected) {
      setShake(id);
      setTimeout(() => setShake(null), 350);
      return;
    }
    onSelect(id);
  };

  return (
    <div className="flex items-center justify-center gap-2 flex-wrap" role="tablist" aria-label="Freya mode">
      {Object.entries(modes).map(([id, m]) => {
        const active = activeMode === id;
        return (
          <button
            key={id}
            role="tab"
            aria-selected={active}
            aria-label={`Switch to ${m.label} mode`}
            onClick={(e) => handleClick(e, id)}
            className="relative overflow-hidden px-4 py-1.5 rounded-full text-[10px] font-semibold tracking-[0.15em] uppercase border transition-all duration-300"
            style={{
              fontFamily: "var(--font-ui)",
              ...(active
                ? {
                    background: "var(--accent-red)",
                    borderColor: "var(--accent-red)",
                    color: "#fff",
                    animation: "pill-breathe 2.6s ease-in-out infinite",
                  }
                : {
                    background: "rgba(18,10,11,0.5)",
                    borderColor: "var(--panel-border)",
                    color: "var(--text-secondary)",
                  }),
              ...(shake === id ? { transform: "translateX(2px)", transition: "transform 0.08s" } : {}),
            }}
            onMouseEnter={(e) => {
              if (!active) (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--panel-border-hover)";
            }}
            onMouseLeave={(e) => {
              if (!active) (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--panel-border)";
            }}
          >
            {m.label}
            {ripples
              .filter((r) => r.key === id)
              .map((r) => (
                <span key={r.id} className="hud-ripple w-8 h-8" style={{ left: r.x, top: r.y }} />
              ))}
          </button>
        );
      })}
    </div>
  );
}
