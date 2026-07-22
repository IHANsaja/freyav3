"use client";

import { useState, useEffect } from "react";
import { AudioDevice, FreyaConfig, FreyaState } from "../hooks/useFreyaSocket";
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
  const [saving, setSaving] = useState(false);

  // Sync state when props load or change
  useEffect(() => {
    if (config?.active_model) setLocalModel(config.active_model);
    if (config?.active_voice) setLocalVoice(config.active_voice);
    if (config?.input_device_index != null) setLocalInputDevice(config.input_device_index);
  }, [config]);

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
      if (localInputDevice !== "" && localInputDevice !== config?.input_device_index && !isRunning) {
        onAudioDeviceChange(localInputDevice);
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
      {/* Modal Container */}
      <div 
        className="w-full max-w-[620px] bg-surface-container-low border border-primary-container/80 flex flex-col"
        style={{ borderRadius: "0px" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant/30">
          <div className="flex items-center gap-2 text-primary font-bold text-xs tracking-wider uppercase">
            <span className="text-sm">⚙</span>
            <span>SYSTEM CONFIGURATION</span>
          </div>
          <button
            onClick={onClose}
            className="text-on-surface-variant hover:text-parchment text-lg font-light transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 flex flex-col gap-6">
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
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Model configuration locked while Freya is active.</p>
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
                          ? "bg-primary-container text-parchment border border-primary-container shadow-[0_0_12px_rgba(211,47,47,0.3)]"
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
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Voice configuration locked while Freya is active.</p>
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
              <p className="text-[10px] text-outline/60 mt-0.5">Note: Mic device locked while Freya is active — stop and restart to apply.</p>
            )}
          </div>

          {/* LONG_TERM_MEMORY_CORE — structured, searchable, editable */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>[⁝]</span>
              <span>LONG_TERM_MEMORY_CORE</span>
            </div>
            <MemoryPanel refreshKey={memoryVersion} />
          </div>

          {/* SKILL_MODULES — capability catalog with gates */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[11px] font-bold text-outline uppercase tracking-wider">
              <span>⌬</span>
              <span>SKILL_MODULES</span>
            </div>
            <SkillsPanel />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-6 px-6 py-4 border-t border-outline-variant/30">
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
                       transition-all tracking-widest uppercase shadow-[0_0_15px_rgba(211,47,47,0.35)]"
          >
            {saving ? "SAVING..." : "COMMIT & SAVE"}
          </button>
        </div>
      </div>
    </div>
  );
}
