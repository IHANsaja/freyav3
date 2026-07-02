"use client";

import { useEffect, useState } from "react";
import { useFreyaSocket } from "./hooks/useFreyaSocket";
import FreyaModel from "./components/FreyaModel";
import SettingsModal from "./components/SettingsModal";
import ActivityIndicator from "./components/ActivityIndicator";
import ApprovalPrompt from "./components/ApprovalPrompt";
import MissionPanel from "./components/MissionPanel";
import SuggestionChips from "./components/SuggestionChips";
import FreyaCore from "./components/FreyaCore";
import CenterCaption from "./components/CenterCaption";
import SceneStage from "./components/SceneStage";

const STATE_LABELS: Record<string, string> = {
  idle: "SYSTEM_STANDBY",
  listening: "LISTENING",
  speaking: "SPEAKING",
  interrupted: "INTERRUPTED",
};

const STATE_COPY: Record<string, string> = {
  idle: "Neural pathways synchronized. Awaiting directive.",
  listening: "Listening. Speak naturally — barge-in enabled.",
  speaking: "Synthesizing response. Interrupt any time.",
  interrupted: "Yielding the floor. Listening.",
};

const FALLBACK_MODES: Record<string, { label: string }> = {
  default: { label: "Default" },
  language_learning: { label: "Language Tutor" },
  coding: { label: "Coding Mode" },
};

export default function Home() {
  const {
    state,
    connected,
    liveText,
    toolLog,
    images,
    newsItems,
    config,
    activeMode,
    micPaused,
    memoryVersion,
    approvals,
    activeMission,
    avatarIntent,
    suggestions,
    contextInfo,
    persona,
    startFreya,
    stopFreya,
    setModel,
    setVoice,
    setMode,
    toggleListening,
    respondApproval,
    cancelMission,
    respondSuggestion,
  } = useFreyaSocket();

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [embodiment, setEmbodiment] = useState<"core" | "figure">("core");
  useEffect(() => {
    const saved = localStorage.getItem("freya_embodiment");
    if (saved === "figure" || saved === "core") setEmbodiment(saved);
  }, []);
  const toggleEmbodiment = () => {
    const next = embodiment === "core" ? "figure" : "core";
    setEmbodiment(next);
    localStorage.setItem("freya_embodiment", next);
  };
  const isRunning = state !== "idle";
  const modes =
    config?.modes && Object.keys(config.modes).length > 0 ? config.modes : FALLBACK_MODES;

  // Persona theme recolors the whole UI via CSS custom properties.
  const personaStyle = persona?.theme?.accent
    ? ({
        "--color-primary": persona.theme.accent,
        "--color-primary-container": persona.theme.accent,
        transition: "all 0.8s ease",
      } as React.CSSProperties)
    : undefined;

  return (
    <main
      className="h-screen max-h-screen overflow-hidden bg-surface text-parchment flex flex-col font-sans selection:bg-primary-container/30 selection:text-parchment"
      style={personaStyle}
    >

      {/* ─── Top Bar ─── */}
      <header className="z-40 border-b border-outline-variant/20 px-8 py-4 flex items-center justify-between bg-surface/70 backdrop-blur-md">
        <div className="flex items-center gap-8">
          <h1 className="text-xl font-black text-primary tracking-widest uppercase">
            F.R.E.Y.A v3.0
          </h1>
          <div className="flex items-center gap-6 text-[10px] tracking-widest font-mono uppercase text-outline">
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full shadow-[0_0_8px] transition-all duration-300 ${
                  connected
                    ? "bg-emerald-400 shadow-emerald-400"
                    : "bg-primary shadow-primary animate-pulse"
                }`}
              />
              <span>{connected ? "CONNECTED" : "OFFLINE"}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span>STATUS:</span>
              <span
                className={
                  state === "interrupted"
                    ? "text-secondary font-bold animate-pulse"
                    : isRunning
                    ? "text-primary font-bold"
                    : "text-outline"
                }
              >
                {STATE_LABELS[state] ?? state.toUpperCase()}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span>MODE:</span>
              <span className="text-primary font-semibold">
                {(modes[activeMode]?.label ?? activeMode).toUpperCase()}
              </span>
            </div>
            {micPaused && (
              <div className="flex items-center gap-1.5 text-secondary font-bold">
                <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
                <span>MIC PAUSED</span>
              </div>
            )}
            {contextInfo && (
              <div className="hidden lg:flex items-center gap-1.5 max-w-[280px]">
                <span>CTX:</span>
                <span className="text-outline/80 truncate normal-case">
                  {contextInfo.app.replace(/\.exe$/i, "")} — {contextInfo.title}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-5">
          <ActivityIndicator active={isRunning} />
          <button
            onClick={toggleEmbodiment}
            className="px-3 py-2 border border-outline-variant/30 hover:border-primary/50 text-[10px] font-mono tracking-widest uppercase text-outline hover:text-parchment transition-all hover:bg-surface-container-high/30"
            title="Switch between the shader core and the humanoid figure"
            style={{ borderRadius: "0px" }}
          >
            {embodiment === "core" ? "CORE" : "FIGURE"}
          </button>
          <button
            onClick={() => setIsSettingsOpen(true)}
            className="p-2 border border-outline-variant/30 hover:border-primary/50 text-outline hover:text-parchment transition-all hover:bg-surface-container-high/30"
            title="Open System Configuration"
            style={{ borderRadius: "0px" }}
          >
            <svg className="w-4.5 h-4.5 fill-current" viewBox="0 0 24 24">
              <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
            </svg>
          </button>
        </div>
      </header>

      {/* ─── Full-bleed Scene Stage (Freya centered) ─── */}
      <div className="flex-1 relative overflow-hidden">

        {/* The 3D embodiment fills the whole stage: shader core or humanoid figure */}
        <div className="absolute inset-0">
          {embodiment === "figure" ? (
            <FreyaModel state={state} avatarIntent={avatarIntent} />
          ) : (
            <FreyaCore state={state} avatarIntent={avatarIntent} persona={persona} />
          )}
        </div>

        {/* Dynamic projection field — the globe scatters & manipulates her outputs */}
        <SceneStage toolLog={toolLog} images={images} newsItems={newsItems} />

        {/* Live captions, layered above the canvas, centered */}
        <CenterCaption state={state} liveText={liveText} />

        {/* Human-in-the-loop approval cards (above the control dock) */}
        <ApprovalPrompt approvals={approvals} onRespond={respondApproval} />

        {/* Live reasoning panel — the active mission's plan and progress */}
        <MissionPanel mission={activeMission} onCancel={cancelMission} />

        {/* Proactive suggestion chips */}
        <SuggestionChips suggestions={suggestions} onRespond={respondSuggestion} />

        {/* ─── Floating control dock (bottom center) ─── */}
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 w-full max-w-[560px] px-4 pointer-events-none z-30">
          <div
            className="pointer-events-auto relative flex flex-col items-center gap-4 px-8 py-5 rounded-2xl"
            style={{
              background:
                "linear-gradient(135deg, rgba(15,10,10,0.6) 0%, rgba(30,10,10,0.5) 100%)",
              backdropFilter: "blur(18px) saturate(140%)",
              WebkitBackdropFilter: "blur(18px) saturate(140%)",
              border: "1px solid rgba(211,47,47,0.18)",
              boxShadow:
                "0 8px 40px rgba(0,0,0,0.6), 0 1px 0 rgba(255,255,255,0.06) inset, 0 0 60px rgba(211,47,47,0.06)",
            }}
          >
            <div
              className="absolute top-0 left-8 right-8 h-px rounded-full"
              style={{
                background:
                  "linear-gradient(90deg, transparent, rgba(211,47,47,0.35), rgba(255,255,255,0.12), rgba(211,47,47,0.35), transparent)",
              }}
            />

            <p className="text-[10px] text-outline leading-relaxed text-center uppercase tracking-widest">
              {STATE_COPY[state] ?? STATE_COPY.idle}
            </p>

            {/* Mode switcher */}
            <div className="flex items-center gap-2 flex-wrap justify-center">
              {Object.entries(modes).map(([id, m]) => (
                <button
                  key={id}
                  onClick={() => setMode(id)}
                  disabled={!connected}
                  className={`px-4 py-1.5 rounded-full text-[10px] font-bold tracking-widest uppercase border transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed ${
                    activeMode === id
                      ? "bg-primary-container text-parchment border-primary-container shadow-[0_0_16px_rgba(211,47,47,0.35)]"
                      : "bg-transparent text-outline border-outline-variant/30 hover:border-primary/60 hover:text-parchment hover:bg-primary/5"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* Start / Stop + Pause-listening */}
            <div className="flex items-center gap-3">
              <button
                onClick={isRunning ? stopFreya : startFreya}
                disabled={!connected}
                className="px-8 py-3 rounded-full text-xs font-bold tracking-widest uppercase transition-all duration-300 shadow-lg bg-primary-container text-parchment hover:bg-primary-container/90 hover:shadow-[0_0_28px_rgba(211,47,47,0.5)] disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isRunning ? "⚡ STOP FREYA" : "⚡ START FREYA"}
              </button>
              <button
                onClick={toggleListening}
                disabled={!connected}
                title="Mute/unmute Freya's mic (Ctrl+Alt+Space)"
                className={`px-5 py-3 rounded-full text-xs font-bold tracking-widest uppercase border transition-all duration-300 disabled:opacity-40 disabled:cursor-not-allowed ${
                  micPaused
                    ? "bg-secondary-container/30 text-secondary border-secondary/60 shadow-[0_0_16px_rgba(146,7,3,0.4)]"
                    : "bg-transparent text-outline border-outline-variant/30 hover:border-primary/60 hover:text-parchment"
                }`}
              >
                {micPaused ? "🔇 RESUME" : "🔊 PAUSE"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Settings modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        state={state}
        config={config}
        memoryVersion={memoryVersion}
        onModelChange={setModel}
        onVoiceChange={setVoice}
      />
    </main>
  );
}
