"use client";

export type EngineState = "offline" | "stopped" | "paused" | "processing" | "listening";

export interface EngineStatus {
  engine: EngineState;
  /** Short label for the header STATUS: readout. */
  statusLabel: string;
  /** Long copy for the status strip under the orb viewport. */
  stripText: string;
  isRunning: boolean;
}

/**
 * Single source of truth mapping raw socket state onto the HUD's engine
 * states. Priority: disconnected > stopped > mic-paused > speaking > listening.
 */
export function useEngineStatus(
  state: string,
  connected: boolean,
  micPaused: boolean
): EngineStatus {
  const isRunning = state !== "idle";

  if (!connected) {
    return { engine: "offline", statusLabel: "OFFLINE", stripText: "FREYA OFFLINE.", isRunning: false };
  }
  if (!isRunning) {
    return { engine: "stopped", statusLabel: "STANDBY", stripText: "STANDBY. PRESS START TO ENGAGE.", isRunning };
  }
  if (micPaused) {
    return { engine: "paused", statusLabel: "PAUSED", stripText: "PAUSED.", isRunning };
  }
  if (state === "speaking") {
    return { engine: "processing", statusLabel: "SPEAKING", stripText: "PROCESSING…", isRunning };
  }
  return {
    engine: "listening",
    statusLabel: state === "interrupted" ? "INTERRUPTED" : "LISTENING",
    stripText: "LISTENING. SPEAK NATURALLY — BARGE-IN ENABLED.",
    isRunning,
  };
}
