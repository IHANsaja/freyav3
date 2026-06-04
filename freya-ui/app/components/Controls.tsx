"use client";

import { FreyaConfig, FreyaState } from "../hooks/useFreyaSocket";

interface ControlsProps {
  state: FreyaState;
  connected: boolean;
  config: FreyaConfig | null;
  onStart: () => void;
  onStop: () => void;
  onModelChange: (model: string) => void;
  onVoiceChange: (voice: string) => void;
}

export default function Controls({
  state,
  connected,
  config,
  onStart,
  onStop,
  onModelChange,
  onVoiceChange,
}: ControlsProps) {
  const isRunning = state !== "idle";

  return (
    <div className="flex flex-col gap-4 p-4 bg-zinc-900 border border-zinc-700 rounded-2xl">

      {/* Connection status */}
      <div className="flex items-center gap-2">
        <span
          className={`w-2 h-2 rounded-full ${
            connected ? "bg-emerald-400" : "bg-red-500"
          }`}
        />
        <span className="text-xs text-zinc-400">
          {connected ? "Connected to Freya server" : "Server disconnected"}
        </span>
      </div>

      {/* Start / Stop */}
      <button
        onClick={isRunning ? onStop : onStart}
        disabled={!connected}
        className={`w-full py-3 rounded-xl font-semibold text-sm transition-all duration-200
          ${
            isRunning
              ? "bg-red-500 hover:bg-red-600 text-white"
              : "bg-emerald-500 hover:bg-emerald-600 text-white"
          }
          disabled:opacity-40 disabled:cursor-not-allowed`}
      >
        {isRunning ? "⏹ Stop Freya" : "▶ Start Freya"}
      </button>

      {/* Freya state badge */}
      <div className="flex justify-center">
        <span
          className={`px-3 py-1 rounded-full text-xs font-medium tracking-wide
            ${state === "listening" ? "bg-blue-500/20 text-blue-400" : ""}
            ${state === "speaking"  ? "bg-purple-500/20 text-purple-400" : ""}
            ${state === "idle"      ? "bg-zinc-700 text-zinc-400" : ""}
          `}
        >
          {state === "idle"      && "● Idle"}
          {state === "listening" && "◎ Listening"}
          {state === "speaking"  && "◉ Speaking"}
        </span>
      </div>

      {/* Divider */}
      <div className="border-t border-zinc-700" />

      {/* Model selector */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-zinc-400 font-medium">Model</label>
        <select
          value={config?.active_model ?? ""}
          onChange={(e) => onModelChange(e.target.value)}
          disabled={isRunning}
          className="bg-zinc-800 border border-zinc-600 text-zinc-200 text-sm
                     rounded-lg px-3 py-2 focus:outline-none focus:ring-1
                     focus:ring-emerald-500 disabled:opacity-40"
        >
          {config?.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.label}
            </option>
          ))}
        </select>
        {isRunning && (
          <p className="text-xs text-zinc-500">Stop Freya to change model</p>
        )}
      </div>

      {/* Voice selector */}
      <div className="flex flex-col gap-1">
        <label className="text-xs text-zinc-400 font-medium">Voice</label>
        <div className="flex gap-2">
          {config?.voices.map((v) => (
            <button
              key={v}
              onClick={() => onVoiceChange(v)}
              disabled={isRunning}
              className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-all
                ${
                  config.active_voice === v
                    ? "bg-emerald-500 text-white"
                    : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                }
                disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

    </div>
  );
}