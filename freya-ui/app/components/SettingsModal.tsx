"use client";

import { useState } from "react";
import { AudioDevice, FreyaConfig, FreyaState } from "../hooks/useFreyaSocket";
import AccessControlPanel from "./AccessControlPanel";
import MemoryPanel from "./MemoryPanel";
import SkillsPanel from "./SkillsPanel";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  state: FreyaState;
  config: FreyaConfig | null;
  audioDevices: { input: AudioDevice[]; output: AudioDevice[] };
  memoryVersion: number;
  onModelChange: (model: string) => void;
  onVoiceChange: (voice: string) => void;
  onAudioDeviceChange: (inputDeviceIndex?: number, outputDeviceIndex?: number) => void;
}

export default function SettingsModal({
  isOpen,
  onClose,
  state,
  config,
  audioDevices,
  memoryVersion,
  onModelChange,
  onVoiceChange,
  onAudioDeviceChange,
}: SettingsModalProps) {
  const isRunning = state !== "idle";

  const [localModel, setLocalModel] = useState("");
  const [localVoice, setLocalVoice] = useState("");
  const [localInputDevice, setLocalInputDevice] = useState<number | "">("");
  const [localOutputDevice, setLocalOutputDevice] = useState<number | "">("");
  const [saving, setSaving] = useState(false);

  // Reset the drafts from config whenever it changes or the modal opens, so
  // DISCARD really discards. Done during render (React's "adjusting state when
  // a prop changes" pattern) rather than in an effect, which would render the
  // stale drafts first.
  const [syncedFrom, setSyncedFrom] = useState<{ config: FreyaConfig | null; isOpen: boolean } | null>(null);
  if (syncedFrom?.config !== config || syncedFrom?.isOpen !== isOpen) {
    setSyncedFrom({ config, isOpen });
    setLocalModel(config?.active_model ?? "");
    setLocalVoice(config?.active_voice ?? "");
    setLocalInputDevice(config?.input_device_index ?? "");
    setLocalOutputDevice(config?.output_device_index ?? "");
  }

  if (!isOpen) return null;

  const handleCommit = async () => {
    setSaving(true);
    try {
      if (localModel !== config?.active_model && !isRunning) {
        onModelChange(localModel);
      }
      if (localVoice !== config?.active_voice && !isRunning) {
        onVoiceChange(localVoice);
      }
      if (!isRunning) {
        const input =
          localInputDevice !== "" && localInputDevice !== config?.input_device_index ? localInputDevice : undefined;
        const output =
          localOutputDevice !== "" && localOutputDevice !== config?.output_device_index ? localOutputDevice : undefined;
        if (input !== undefined || output !== undefined) onAudioDeviceChange(input, output);
      }
      onClose();
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-container-lowest/80 backdrop-blur-sm p-4">
      {/* Modal Container — wide on desktop, full-width on small screens, and
          never taller than the viewport (the body scrolls instead, which the
          old fixed-height single column could not do). */}
      <div
        className="w-full max-w-[1100px] max-h-[92vh] bg-surface-container-low border border-primary-container/80 flex flex-col"
        style={{ borderRadius: "0px" }}
      >
        {/* Header */}
        <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-outline-variant/30">
          <div className="flex items-center gap-2 text-primary font-bold text-xs tracking-wider uppercase">
            <span className="text-sm">⚙</span>
            <span>SYSTEM CONFIGURATION</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="text-on-surface-variant hover:text-parchment text-lg font-light transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content Body — two columns of settings on wide screens, stacked on
            narrow ones; scrolls independently of the header/footer. */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6 grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-6 items-start">
          {/* PRIMARY_LLM_ARCHITECTURE */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>🌐</span>
              <span>PRIMARY_LLM_ARCHITECTURE</span>
            </div>
            <div className="relative">
              <select
                value={localModel}
                onChange={(e) => setLocalModel(e.target.value)}
                disabled={isRunning}
                className="w-full bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-xs
                           px-4 py-3 focus:outline-none focus:border-primary-container disabled:opacity-40
                           appearance-none font-mono tracking-wider uppercase cursor-pointer"
                style={{ borderRadius: "0px" }}
              >
                {config?.models.map((m) => (
                  <option key={m.id} value={m.id} className="bg-surface-container-lowest text-on-surface">
                    {m.label.toUpperCase()}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-primary">
                <span className="text-[10px]">▼</span>
              </div>
            </div>
            {isRunning && (
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Model configuration locked while Freyja is active.</p>
            )}
          </div>

          {/* VOCAL_SYNTHESIS_ENGINE */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>🗣</span>
              <span>VOCAL_SYNTHESIS_ENGINE</span>
            </div>
            <div className="flex gap-3">
              {config?.voices.map((v) => {
                const isActive = localVoice === v;
                return (
                  <button
                    key={v}
                    onClick={() => setLocalVoice(v)}
                    disabled={isRunning}
                    className={`px-6 py-2 rounded-full text-xs font-semibold tracking-wider transition-all duration-200
                      ${
                        isActive
                          ? "bg-primary-container text-parchment border border-primary-container shadow-[0_0_12px_rgba(15,156,110,0.3)]"
                          : "bg-transparent text-on-surface-variant border border-outline-variant/40 hover:bg-surface-container-high hover:text-on-surface"
                      }
                      disabled:opacity-40 disabled:cursor-not-allowed`}
                  >
                    {v}
                  </button>
                );
              })}
            </div>
            {isRunning && (
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Voice configuration locked while Freyja is active.</p>
            )}
          </div>

          {/* AUDIO_INPUT_DEVICE — which mic PyAudio captures on the backend */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>🎙</span>
              <span>AUDIO_INPUT_DEVICE</span>
            </div>
            <div className="relative">
              <select
                value={localInputDevice}
                onChange={(e) => setLocalInputDevice(e.target.value === "" ? "" : Number(e.target.value))}
                disabled={isRunning || audioDevices.input.length === 0}
                className="w-full bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-xs
                           px-4 py-3 focus:outline-none focus:border-primary-container disabled:opacity-40
                           appearance-none font-mono tracking-wider uppercase cursor-pointer"
                style={{ borderRadius: "0px" }}
              >
                {audioDevices.input.length === 0 && <option value="">NO INPUT DEVICES FOUND</option>}
                {audioDevices.input.map((d) => (
                  <option key={d.index} value={d.index} className="bg-surface-container-lowest text-on-surface">
                    [{d.index}] {d.name}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-primary">
                <span className="text-[10px]">▼</span>
              </div>
            </div>
            {isRunning && (
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Mic device locked while Freyja is active — stop and restart to apply.</p>
            )}
          </div>

          {/* AUDIO_OUTPUT_DEVICE — which speaker PyAudio plays her voice on */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>🔊</span>
              <span>AUDIO_OUTPUT_DEVICE</span>
            </div>
            <div className="relative">
              <select
                aria-label="Audio output device"
                value={localOutputDevice}
                onChange={(e) => setLocalOutputDevice(e.target.value === "" ? "" : Number(e.target.value))}
                disabled={isRunning || audioDevices.output.length === 0}
                className="w-full bg-surface-container-lowest border border-outline-variant/40 text-on-surface text-xs
                           px-4 py-3 focus:outline-none focus:border-primary-container disabled:opacity-40
                           appearance-none font-mono tracking-wider uppercase cursor-pointer"
                style={{ borderRadius: "0px" }}
              >
                {audioDevices.output.length === 0 && <option value="">NO OUTPUT DEVICES FOUND</option>}
                {audioDevices.output.map((d) => (
                  <option key={d.index} value={d.index} className="bg-surface-container-lowest text-on-surface">
                    [{d.index}] {d.name}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-primary">
                <span className="text-[10px]">▼</span>
              </div>
            </div>
            {isRunning && (
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Speaker device locked while Freyja is active — stop and restart to apply.</p>
            )}
          </div>

          {/* ACCESS_CONTROL — which folders Freya may read/write/delete in.
              Editable here so it doesn't require hand-editing the JSON config. */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>🔐</span>
              <span>ACCESS_CONTROL</span>
            </div>
            <AccessControlPanel />
          </div>

          {/* LONG_TERM_MEMORY_CORE — structured, searchable, editable */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>[⁝]</span>
              <span>LONG_TERM_MEMORY_CORE</span>
            </div>
            <MemoryPanel refreshKey={memoryVersion} />
          </div>

          {/* SKILL_MODULES — capability catalog with gates. Full width: the
              catalog is long and reads better across the modal. */}
          <div className="flex flex-col gap-2 lg:col-span-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>⌬</span>
              <span>SKILL_MODULES</span>
            </div>
            <SkillsPanel />
          </div>
        </div>

        {/* Footer */}
        <div className="shrink-0 flex items-center justify-end gap-6 px-6 py-4 border-t border-outline-variant/30">
          <button
            onClick={onClose}
            className="text-xs font-semibold text-on-surface-variant hover:text-parchment uppercase tracking-widest transition-colors"
          >
            DISCARD
          </button>
          <button
            onClick={handleCommit}
            disabled={saving}
            className="px-6 py-2.5 rounded-full text-xs font-semibold text-parchment bg-primary-container hover:bg-primary-container/90
                       transition-all tracking-widest uppercase shadow-[0_0_15px_rgba(15,156,110,0.35)]"
          >
            {saving ? "SAVING..." : "COMMIT & SAVE"}
          </button>
        </div>
      </div>
    </div>
  );
}
