"use client";

interface WaveformProps {
  active: boolean;
  bars?: number;
  size?: "sm" | "md";
}

const HEIGHTS_SM = [12, 8, 16, 6, 10];
const HEIGHTS_MD = [18, 12, 24, 9, 15, 20, 11];
const DURATIONS = [1.2, 0.8, 1.5, 1.0, 1.3, 0.9, 1.4];
const DELAYS = [0, 0.2, 0.4, 0.1, 0.3, 0.15, 0.35];

/** Reusable animated bar-waveform — audio/data-stream indicator. */
export default function Waveform({ active, bars = 5, size = "sm" }: WaveformProps) {
  const heights = (size === "sm" ? HEIGHTS_SM : HEIGHTS_MD).slice(0, bars);
  return (
    <div className="flex items-end gap-[3px] h-6" title={active ? "Live audio stream" : "Idle"}>
      {heights.map((h, i) => (
        <span
          key={i}
          className="w-[1.5px] origin-bottom"
          style={{
            height: h,
            background: active ? "var(--color-primary)" : "var(--hud-line-strong)",
            animation: active
              ? `pulse-line ${DURATIONS[i % DURATIONS.length]}s ease-in-out infinite ${DELAYS[i % DELAYS.length]}s`
              : "none",
            opacity: active ? 1 : 0.4,
            transform: active ? undefined : "scaleY(0.35)",
          }}
        />
      ))}
    </div>
  );
}
