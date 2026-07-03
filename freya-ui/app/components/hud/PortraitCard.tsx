"use client";

import { useCallback, useEffect, useState } from "react";
import type { AvatarIntent } from "../../hooks/useFreyaSocket";
import type { EngineState } from "../../hooks/useEngineStatus";
import type { ExpressionEvent } from "../avatar/AvatarController";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import PortraitScene from "../scene/PortraitScene";
import HudCard from "./HudCard";
import Waveform from "./Waveform";

interface PortraitCardProps {
  state: string;
  avatarIntent: AvatarIntent | null;
  engine: EngineState;
  onExpressionChange: (e: ExpressionEvent | null) => void;
}

/** Live 3D Freya portrait — the "surveillance feed" card, top-left. */
export default function PortraitCard({ state, avatarIntent, engine, onExpressionChange }: PortraitCardProps) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [glitchTick, setGlitchTick] = useState(0);
  const reduced = useReducedMotion();

  const handleLoading = useCallback((l: boolean) => setLoading(l), []);
  const handleError = useCallback(() => setFailed(true), []);

  // Occasional horizontal glitch-line sweep (every 8–12s) for feed texture.
  useEffect(() => {
    if (reduced || failed) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        setGlitchTick((t) => t + 1);
        schedule();
      }, 8000 + Math.random() * 4000);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [reduced, failed]);

  return (
    <HudCard className="flex-1 min-h-[210px] max-h-[340px]" bodyClassName="relative" title={undefined}>
      <div className="absolute inset-0 overflow-hidden" style={{ borderRadius: "calc(var(--radius) - 2px)" }}>
        {/* Viewport */}
        {!failed ? (
          <PortraitScene
            state={state}
            avatarIntent={avatarIntent}
            onLoading={handleLoading}
            onError={handleError}
            onExpressionChange={onExpressionChange}
          />
        ) : (
          // Graceful degradation: dark animated gradient + silhouette, same chrome.
          <div
            aria-hidden
            className="absolute inset-0 flex items-center justify-center"
            style={{
              background: "linear-gradient(160deg, #120a0c 0%, #1c0d10 50%, #0a0608 100%)",
            }}
          >
            <svg viewBox="0 0 100 120" className="w-32 opacity-25" fill="var(--accent-red-dim)">
              <circle cx="50" cy="38" r="20" />
              <path d="M14 120 C14 88 32 74 50 74 C68 74 86 88 86 120 Z" />
            </svg>
            <p
              className="absolute bottom-16 text-[9px] tracking-[0.2em] font-mono"
              style={{ color: "var(--text-tertiary)" }}
            >
              SIGNAL LOST — VISUAL FEED UNAVAILABLE
            </p>
          </div>
        )}

        {/* Diegetic loading state */}
        {loading && !failed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-[rgba(7,5,10,0.7)]">
            <p className="text-[10px] tracking-[0.25em] font-mono hud-flicker" style={{ color: "var(--accent-red)" }}>
              CALIBRATING…
            </p>
            <div className="w-24 h-px relative overflow-hidden" style={{ background: "var(--accent-red-dim)" }}>
              <div
                className="absolute inset-y-0 w-1/3"
                style={{
                  background: "var(--accent-red)",
                  animation: "row-sweep 1.1s ease-in-out infinite",
                }}
              />
            </div>
          </div>
        )}

        {/* Surveillance-feed texture: scanlines, vignette, glitch line */}
        {!failed && (
          <>
            <div aria-hidden className="hud-scanlines" />
            <div
              aria-hidden
              className="absolute inset-0 pointer-events-none"
              style={{ background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.55) 100%)" }}
            />
            {glitchTick > 0 && (
              <div
                aria-hidden
                key={glitchTick}
                className="absolute inset-x-0 h-px pointer-events-none"
                style={{
                  background: "linear-gradient(90deg, transparent, rgba(255,120,130,0.7), rgba(255,255,255,0.4), transparent)",
                  animation: "glitch-line 0.5s linear forwards",
                }}
              />
            )}
          </>
        )}

        {/* Footer chrome — layered above the viewport, never clipped by 3D */}
        <div className="absolute inset-x-0 bottom-0 px-4 pb-3 pt-8 pointer-events-none bg-gradient-to-t from-[rgba(7,5,10,0.85)] to-transparent">
          <p
            className="text-lg font-bold tracking-[0.12em]"
            style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}
          >
            F.R.E.Y.A
          </p>
          <p className="text-[8px] tracking-[0.18em] uppercase mt-0.5" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-ui)" }}>
            Field Response &amp; Exploration Analytic
          </p>
          <div className="mt-2">
            <Waveform active={engine === "processing" || engine === "listening"} bars={5} />
          </div>
        </div>
      </div>
    </HudCard>
  );
}
