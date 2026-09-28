"use client";

import { ReactNode } from "react";
import type { EngineStatus } from "../../hooks/useEngineStatus";
import StatusStrip from "./StatusStrip";
import ModeTabs from "./ModeTabs";
import ActionButtons from "./ActionButtons";
import TelemetryCallouts, { type CalloutEvent } from "./TelemetryCallouts";
import RuneInscription from "../runes/RuneInscription";
import RuneRing from "../runes/RuneRing";

interface CenterStageProps {
  status: EngineStatus;
  modes: Record<string, { label: string }>;
  activeMode: string;
  connected: boolean;
  micPaused: boolean;
  calloutEvent: CalloutEvent | null;
  onSelectMode: (id: string) => void;
  onToggleRun: () => void;
  onTogglePause: () => void;
  /** She is actively working (a tool, thinking, speaking): the runes charge. */
  charged?: boolean;
  /** Live-caption overlay (CenterCaption) rendered inside the viewport. */
  children?: ReactNode;
}

const BRACKET = "absolute w-5 h-5 border-[var(--accent-red)] opacity-50 pointer-events-none";

/** The center column: bracket-framed orb viewport (transparent — the WebGL
 *  stage shows through from behind), status strip, mode tabs, actions. */
export default function CenterStage({
  status,
  modes,
  activeMode,
  connected,
  micPaused,
  calloutEvent,
  onSelectMode,
  onToggleRun,
  onTogglePause,
  charged = false,
  children,
}: CenterStageProps) {
  const charge: 0 | 1 | 2 =
    status.engine === "offline" || status.engine === "stopped" ? 0 : charged || status.engine === "processing" ? 2 : 1;
  return (
    <div className="hud-col-center flex flex-col gap-4 min-h-0 h-full pointer-events-none">
      {/* Orb viewport frame — transparent middle so the canvas reads through */}
      <div className="relative flex-1 min-h-[280px]">
        <div aria-hidden className="absolute inset-0 border rounded-[var(--radius)]" style={{ borderColor: "var(--panel-border)" }} />
        <span aria-hidden className={`${BRACKET} top-0 left-0 border-t-2 border-l-2`} />
        <span aria-hidden className={`${BRACKET} top-0 right-0 border-t-2 border-r-2`} />
        <span aria-hidden className={`${BRACKET} bottom-0 left-0 border-b-2 border-l-2`} />
        <span aria-hidden className={`${BRACKET} bottom-0 right-0 border-b-2 border-r-2`} />

        {/* Runic carving: the futhark ring around the orb, inscription bands
            along the frame. Behind everything, never interactive. */}
        <div aria-hidden className="absolute inset-0 overflow-hidden rounded-[var(--radius)] pointer-events-none">
          <RuneRing charge={charge} className="absolute left-1/2 top-[56%] -translate-x-1/2 -translate-y-1/2 w-[min(70%,55vh)] aspect-square" />
          <RuneInscription charged={charge === 2} className="absolute top-2 inset-x-6 text-[11px]" />
          <RuneInscription charged={charge === 2} offset={12} className="absolute bottom-2 inset-x-6 text-[11px]" />
        </div>

        <TelemetryCallouts event={calloutEvent} modeId={activeMode} />
        {children}
      </div>

      {/* Controls — interactive, so pointer events come back on */}
      <div className="flex flex-col gap-3 pointer-events-auto pb-1">
        <StatusStrip text={status.stripText} />
        <ModeTabs modes={modes} activeMode={activeMode} connected={connected} onSelect={onSelectMode} />
        <ActionButtons
          isRunning={status.isRunning}
          micPaused={micPaused}
          connected={connected}
          onToggleRun={onToggleRun}
          onTogglePause={onTogglePause}
        />
      </div>
    </div>
  );
}
