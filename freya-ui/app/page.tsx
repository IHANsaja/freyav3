"use client";

import { useFreyaSocket } from "./hooks/useFreyaSocket";
import Controls from "./components/Controls";
import Transcription from "./components/Transcription";
import ToolLog from "./components/ToolLog";
import MemoryEditor from "./components/MemoryEditor";

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

  return (
    <main className="min-h-screen bg-zinc-950 text-white p-4">

      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">
            F.R.E.Y.A
          </h1>
          <p className="text-xs text-zinc-500">
            Fully Responsive Engineered Yielding Assistant — v3.0
          </p>
        </div>
        <div
          className={`text-xs px-3 py-1 rounded-full font-medium
            ${state === "speaking"  ? "bg-purple-500/20 text-purple-400 animate-pulse" : ""}
            ${state === "listening" ? "bg-blue-500/20 text-blue-400 animate-pulse" : ""}
            ${state === "idle"      ? "bg-zinc-800 text-zinc-500" : ""}
          `}
        >
          {state.toUpperCase()}
        </div>
      </div>

      {/* Layout: 3 columns */}
      <div className="grid grid-cols-12 gap-4 h-[calc(100vh-80px)]">

        {/* Left — Controls */}
        <div className="col-span-3 flex flex-col gap-4">
          <Controls
            state={state}
            connected={connected}
            config={config}
            onStart={startFreya}
            onStop={stopFreya}
            onModelChange={setModel}
            onVoiceChange={setVoice}
          />
        </div>

        {/* Center — Transcription */}
        <div className="col-span-6">
          <Transcription
            transcript={transcript}
            onClear={clearTranscript}
          />
        </div>

        {/* Right — Tool Log + Memory Editor */}
        <div className="col-span-3 flex flex-col gap-4">
          <div className="flex-1">
            <ToolLog
              toolLog={toolLog}
              onClear={clearToolLog}
            />
          </div>
          <div className="flex-1">
            <MemoryEditor
              memory={memory}
              onSave={saveMemory}
            />
          </div>
        </div>

      </div>
    </main>
  );
}