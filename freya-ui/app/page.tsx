"use client";

import { useState } from "react";
import { useFreyaSocket } from "./hooks/useFreyaSocket";
import SettingsModal from "./components/SettingsModal";
import ArchivalPanel from "./components/ArchivalPanel";
import ActivityIndicator from "./components/ActivityIndicator";
import FreyaModel from "./components/FreyaModel";

export default function Home() {
  const {
    state,
    connected,
    transcript,
    toolLog,
    config,
    memory,
    startFreya,
    stopFreya,
    setModel,
    setVoice,
    saveMemory,
    clearTranscript,
    clearToolLog,
  } = useFreyaSocket();

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const isRunning = state !== "idle";

  return (
    <main className="h-screen max-h-screen overflow-hidden bg-surface text-parchment flex flex-col font-sans selection:bg-primary-container/30 selection:text-parchment">
      
      {/* Top Header Bar */}
      <header className="border-b border-outline-variant/20 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-8">
          {/* Logo */}
          <div className="flex flex-col">
            <h1 className="text-xl font-black text-primary tracking-widest font-sans uppercase">
              F.R.E.Y.A v3.0
            </h1>
          </div>
 
          {/* Connection status tag */}
          <div className="flex items-center gap-6 text-[10px] tracking-widest font-mono uppercase text-outline">
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full shadow-[0_0_8px] transition-all duration-300 ${
                  connected
                    ? "bg-emerald-400 shadow-emerald-400"
                    : "bg-primary shadow-primary animate-pulse"
                }`}
              />
              <span>{connected ? "CONNECTED_TO_SERVER" : "SERVER_OFFLINE"}</span>
            </div>

            <div className="flex items-center gap-1.5">
              <span>STATUS:</span>
              <span className={isRunning ? "text-primary font-bold" : "text-outline"}>
                {state.toUpperCase()}
              </span>
            </div>
          </div>
        </div>

        {/* Right side controls */}
        <div className="flex items-center gap-5">
          {/* Activity indicator */}
          <ActivityIndicator active={isRunning} />

          {/* Icon buttons */}
          <div className="flex items-center gap-3">
            {/* System config settings icon button */}
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
        </div>
      </header>

      {/* Main Layout Grid */}
      <div className="flex-1 grid grid-cols-12 overflow-hidden">
        
        {/* Left Column — Metadata Sidebar */}
        <div className="col-span-2 p-8 border-r border-outline-variant/10 flex flex-col gap-6 font-mono text-[10px] tracking-widest text-outline uppercase select-none">
          <div className="flex flex-col gap-1">
            <span className="text-outline-variant font-bold">LATITUDE</span>
            <span className="text-parchment font-semibold">40.7128° N</span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-outline-variant font-bold">LONGITUDE</span>
            <span className="text-parchment font-semibold">74.0060° W</span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-outline-variant font-bold">ENCRYPTION</span>
            <span className="text-parchment font-semibold">AES_256_GCM</span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-outline-variant font-bold">CORE_ARCHV</span>
            <span className="text-parchment font-semibold">V3.0.0_STABLE</span>
          </div>
        </div>

        {/* Center Column — Companion space with Freya 3D Model */}
        <div className="col-span-6 p-8 flex flex-col justify-between items-center relative">
          
          {/* Middle 3D Companion Area */}
          <div className="flex-1 flex items-center justify-center w-full max-w-lg">
            <FreyaModel state={state} toolLog={toolLog} />
          </div>

          {/* System Standby Details & Start/Stop Controls */}
          <div className="w-full max-w-xl text-center mb-16 flex flex-col items-center gap-6">
            <div className="flex flex-col gap-2">
              <h2 className="text-3xl font-black text-parchment tracking-widest uppercase">
                {isRunning ? "SYSTEM_ACTIVE" : "SYSTEM_STANDBY"}
              </h2>
              <p className="text-xs text-outline leading-relaxed max-w-md mx-auto uppercase tracking-wide">
                {isRunning 
                  ? "Archival core fully synchronized. Acoustic neural pathways engaged. Streaming telemetry logs to local stdout."
                  : "Archival core v3.0.0-STABLE operational. Neural pathways synchronized for directive input."
                }
              </p>
            </div>

            {/* Pulsing trigger button */}
            <button
              onClick={isRunning ? stopFreya : startFreya}
              disabled={!connected}
              className={`px-8 py-3.5 rounded-full text-xs font-bold tracking-widest uppercase transition-all duration-300 shadow-lg
                ${
                  isRunning
                    ? "bg-primary-container text-parchment hover:bg-primary-container/95 hover:shadow-[0_0_20px_rgba(211,47,47,0.4)]"
                    : "bg-primary-container text-parchment hover:bg-primary-container/95 hover:shadow-[0_0_20px_rgba(211,47,47,0.4)]"
                }
                disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              {isRunning ? "⚡ STOP FREYA" : "⚡ START FREYA"}
            </button>

            {/* Footer tag */}
            <div className="text-[9px] font-bold text-outline-variant tracking-widest uppercase font-mono mt-4">
              DEVELOPED BY &bull; IHAN &bull; 2026
            </div>
          </div>
        </div>

        {/* Right Column — Archival Panel (Conversation Terminal + Memory + Tools) */}
        <div className="col-span-4 h-full overflow-hidden">
          <ArchivalPanel
            state={state}
            transcript={transcript}
            toolLog={toolLog}
            memory={memory}
            onClearTranscript={clearTranscript}
            onClearToolLog={clearToolLog}
            onOpenSettings={() => setIsSettingsOpen(true)}
          />
        </div>

      </div>

      {/* System Settings configuration modal popup */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        state={state}
        config={config}
        memory={memory}
        onModelChange={setModel}
        onVoiceChange={setVoice}
        onSaveMemory={saveMemory}
      />
    </main>
  );
}