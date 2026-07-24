"use client";

import { MouseEvent, ReactNode, useRef, useState } from "react";

interface ActionButtonsProps {
  isRunning: boolean;
  micPaused: boolean;
  connected: boolean;
  onToggleRun: () => void;
  onTogglePause: () => void;
}

/** Magnetic-hover wrapper: the button drifts a few px toward the cursor. */
function Magnetic({
  children,
  onClick,
  ariaLabel,
  className,
  style,
  disabled,
}: {
  children: ReactNode;
  onClick: (e: MouseEvent<HTMLButtonElement>) => void;
  ariaLabel: string;
  className?: string;
  style?: React.CSSProperties;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([]);

  const onMove = (e: MouseEvent<HTMLButtonElement>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const dx = (e.clientX - (rect.left + rect.width / 2)) / rect.width;
    const dy = (e.clientY - (rect.top + rect.height / 2)) / rect.height;
    el.style.transform = `translate(${dx * 6}px, ${dy * 5}px)`;
  };
  const onLeave = () => {
    if (ref.current) ref.current.style.transform = "";
  };
  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setRipples((r) => [...r.slice(-2), { id: Date.now(), x: e.clientX - rect.left, y: e.clientY - rect.top }]);
    onClick(e);
  };

  return (
    <button
      ref={ref}
      onClick={handleClick}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      aria-label={ariaLabel}
      disabled={disabled}
      className={`relative overflow-hidden transition-shadow duration-300 will-change-transform disabled:opacity-40 disabled:cursor-not-allowed ${className ?? ""}`}
      style={style}
    >
      {children}
      {ripples.map((r) => (
        <span key={r.id} className="hud-ripple w-12 h-12" style={{ left: r.x, top: r.y }} />
      ))}
    </button>
  );
}

/** The two primary controls: STOP/START FREYA (dominant) + PAUSE/RESUME. */
export default function ActionButtons({ isRunning, micPaused, connected, onToggleRun, onTogglePause }: ActionButtonsProps) {
  return (
    <div className="flex items-center justify-center gap-4">
      <Magnetic
        onClick={onToggleRun}
        ariaLabel={isRunning ? "Stop Freya" : "Start Freya"}
        disabled={!connected}
        className="group px-9 py-3.5 rounded-full text-xs font-bold tracking-[0.2em] uppercase"
        style={{
          fontFamily: "var(--font-ui)",
          background: "linear-gradient(180deg, var(--accent-red) 0%, #c81828 100%)",
          color: "#fff",
          boxShadow: "0 0 24px rgba(34,224,160,0.4), inset 0 1px 0 rgba(255,255,255,0.25)",
        }}
      >
        <span className="flex items-center gap-2">
          {/* Target-ring glyph — rotates gently on hover */}
          <svg viewBox="0 0 16 16" className="w-4 h-4 transition-transform duration-500 group-hover:rotate-90" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
            <circle cx="8" cy="8" r="5.5" />
            <circle cx="8" cy="8" r="1.6" fill="currentColor" stroke="none" />
            <path d="M8 1v2.2 M8 12.8V15 M1 8h2.2 M12.8 8H15" />
          </svg>
          {isRunning ? "STOP FREYA" : "START FREYA"}
        </span>
      </Magnetic>

      <Magnetic
        onClick={onTogglePause}
        ariaLabel={micPaused ? "Resume listening" : "Pause listening"}
        disabled={!connected}
        className="group px-7 py-3.5 rounded-full text-xs font-bold tracking-[0.2em] uppercase border hover:border-[var(--panel-border-hover)]"
        style={{
          fontFamily: "var(--font-ui)",
          background: "rgba(18,10,11,0.55)",
          borderColor: micPaused ? "var(--accent-red)" : "var(--panel-border)",
          color: micPaused ? "var(--accent-red-glow)" : "var(--text-secondary)",
        }}
      >
        <span className="flex items-center gap-2">
          <svg viewBox="0 0 16 16" className="w-3.5 h-3.5 transition-transform duration-300 group-hover:scale-110" fill="currentColor" aria-hidden>
            {micPaused ? <path d="M5 3l8 5-8 5z" /> : <path d="M4.5 3h2.5v10H4.5z M9 3h2.5v10H9z" />}
          </svg>
          {micPaused ? "RESUME" : "PAUSE"}
        </span>
      </Magnetic>
    </div>
  );
}
