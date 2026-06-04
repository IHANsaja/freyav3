"use client";

import { useState, useEffect, useRef } from "react";
import { TranscriptEntry, ToolEntry, FreyaState } from "../hooks/useFreyaSocket";

interface ArchivalPanelProps {
  state: FreyaState;
  transcript: TranscriptEntry[];
  toolLog: ToolEntry[];
  memory: string;
  onClearTranscript: () => void;
  onClearToolLog: () => void;
  onOpenSettings: () => void;
}

type TabType = "conversations" | "memory" | "tools";

export default function ArchivalPanel({
  state,
  transcript,
  toolLog,
  memory,
  onClearTranscript,
  onClearToolLog,
  onOpenSettings,
}: ArchivalPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>("conversations");
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom of conversation logs
  useEffect(() => {
    if (activeTab === "conversations") {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [transcript, activeTab]);

  return (
    <div className="w-full h-full flex flex-col bg-surface border-l border-outline-variant/30 text-parchment">
      {/* System Identification */}
      <div className="px-6 py-6 border-b border-outline-variant/20 flex flex-col gap-1">
        <h2 className="text-lg font-bold tracking-widest text-parchment uppercase font-sans">
          ARCHIVAL_SYSTEM
        </h2>
        <span className="text-[10px] font-semibold text-outline tracking-widest font-mono uppercase">
          v3.0.0-STABLE
        </span>
      </div>

      {/* Navigation tabs */}
      <div className="flex flex-col border-b border-outline-variant/20 font-mono text-xs">
        {/* Tab 1: CONVERSATIONS */}
        <button
          onClick={() => setActiveTab("conversations")}
          className={`flex items-center gap-3 px-6 py-3.5 transition-all text-left uppercase tracking-widest font-bold
            ${
              activeTab === "conversations"
                ? "bg-secondary-container text-parchment border-r-4 border-primary"
                : "text-on-surface-variant hover:bg-surface-container/30 hover:text-parchment"
            }`}
          style={{ borderRadius: "0px" }}
        >
          {/* SVG Console Icon */}
          <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
            <path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm-8 12H4v-2h8v2zm8-4H4V8h16v4zm0-4H4V6h16v2z" />
          </svg>
          <span>CONVERSATIONS</span>
        </button>

        {/* Tab 2: SEE_HER_MEMORY */}
        <button
          onClick={() => setActiveTab("memory")}
          className={`flex items-center gap-3 px-6 py-3.5 transition-all text-left uppercase tracking-widest font-bold
            ${
              activeTab === "memory"
                ? "bg-secondary-container text-parchment border-r-4 border-primary"
                : "text-on-surface-variant hover:bg-surface-container/30 hover:text-parchment"
            }`}
          style={{ borderRadius: "0px" }}
        >
          {/* SVG Chip/Memory Icon */}
          <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
            <path d="M21 2H3c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM9 18H5v-4h4v4zm0-6H5V8h4v4zm6 6h-4v-4h4v4zm0-6h-4V8h4v4zm6 6h-4v-4h4v4zm0-6h-4V8h4v4z" />
          </svg>
          <span>SEE_HER_MEMORY</span>
        </button>

        {/* Tab 3: TOOL_SETS_AND_EDIT */}
        <button
          onClick={() => setActiveTab("tools")}
          className={`flex items-center gap-3 px-6 py-3.5 transition-all text-left uppercase tracking-widest font-bold
            ${
              activeTab === "tools"
                ? "bg-secondary-container text-parchment border-r-4 border-primary"
                : "text-on-surface-variant hover:bg-surface-container/30 hover:text-parchment"
            }`}
          style={{ borderRadius: "0px" }}
        >
          {/* SVG Tools Icon */}
          <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
            <path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.3C.5 6.7.9 9.8 2.9 11.8c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.6z" />
          </svg>
          <span>TOOL_SETS_AND_EDIT</span>
        </button>
      </div>

      {/* Main tab content container */}
      <div className="flex-1 min-h-0 flex flex-col p-6 font-mono text-xs overflow-y-auto">
        {/* VIEW 1: CONVERSATIONS TERMINAL LOG */}
        {activeTab === "conversations" && (
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-between text-[10px] text-primary font-bold uppercase tracking-wider mb-4">
              <span>[SESSION_ACTIVE] NODE_01_SYNCHRONIZED</span>
              <button
                onClick={onClearTranscript}
                className="text-[9px] text-outline hover:text-parchment border border-outline-variant/30 px-2 py-0.5 transition-colors uppercase"
                style={{ borderRadius: "0px" }}
              >
                Clear_Terminal
              </button>
            </div>

            <div className="flex-1 overflow-y-auto flex flex-col gap-3 font-mono leading-relaxed pr-1 text-on-surface">
              {transcript.length === 0 ? (
                <div className="text-outline-variant italic mt-2 uppercase">
                  No transmission active. Standing by...
                </div>
              ) : (
                transcript.map((entry) => (
                  <div key={entry.id} className="flex flex-col gap-0.5">
                    <div>
                      <span
                        className={
                          entry.speaker === "Ihan"
                            ? "text-outline font-bold"
                            : "text-primary font-bold"
                        }
                      >
                        {entry.speaker === "Ihan" ? "Ihan (STT)" : "Freya (TTS)"}:
                      </span>{" "}
                      <span className="text-parchment">{entry.text}</span>
                    </div>
                  </div>
                ))
              )}
              {state === "listening" && (
                <div className="text-outline animate-pulse uppercase">
                  ● Freya listening...
                </div>
              )}
              {state === "speaking" && (
                <div className="text-primary animate-pulse uppercase">
                  ● Freya speaking...
                </div>
              )}
              <div className="flex items-center mt-2">
                <span className="text-primary mr-1">&gt;</span>
                <span className="terminal-cursor"></span>
              </div>
              <div ref={bottomRef} />
            </div>
          </div>
        )}

        {/* VIEW 2: SEE HER MEMORY READ-ONLY VIEW */}
        {activeTab === "memory" && (
          <div className="flex flex-col h-full gap-4">
            <div className="flex items-center justify-between text-[10px] text-primary font-bold uppercase tracking-wider">
              <span>MEM_CORE_DUMP_01</span>
              <button
                onClick={onOpenSettings}
                className="text-[9px] text-primary border border-primary-container px-3 py-1 transition-all hover:bg-primary-container/20 uppercase tracking-wider"
                style={{ borderRadius: "0px" }}
              >
                Edit_Context
              </button>
            </div>

            <div className="flex-1 bg-surface-container-lowest/50 border border-outline-variant/20 p-4 overflow-y-auto text-[11px] leading-relaxed uppercase text-on-surface font-mono whitespace-pre-wrap">
              {memory ? memory : "NO MEMORY REGISTERED IN SYSTEM CONFIGURATION."}
            </div>
          </div>
        )}

        {/* VIEW 3: TOOL SETS AND EDIT (ACTIVITY LOG) */}
        {activeTab === "tools" && (
          <div className="flex flex-col h-full">
            <div className="flex items-center justify-between text-[10px] text-primary font-bold uppercase tracking-wider mb-4">
              <span>TOOL_COMPUTATIONAL_LOG</span>
              <button
                onClick={onClearToolLog}
                className="text-[9px] text-outline hover:text-parchment border border-outline-variant/30 px-2 py-0.5 transition-colors uppercase"
                style={{ borderRadius: "0px" }}
              >
                Clear_Log
              </button>
            </div>

            <div className="flex-1 overflow-y-auto flex flex-col gap-3 pr-1">
              {toolLog.length === 0 ? (
                <div className="text-outline-variant italic uppercase">
                  No external tool operations registered in stack.
                </div>
              ) : (
                [...toolLog].reverse().map((entry) => (
                  <div
                    key={entry.id}
                    className="border border-outline-variant/30 bg-surface-container-lowest p-3 flex flex-col gap-1.5"
                    style={{ borderRadius: "0px" }}
                  >
                    <div className="flex items-center justify-between font-bold text-[10px]">
                      <span className="text-primary uppercase tracking-wider">
                        {entry.name}
                      </span>
                      <span className="text-outline-variant">
                        {entry.timestamp.toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })}
                      </span>
                    </div>

                    {Object.keys(entry.args).length > 0 && (
                      <div className="text-[10px] text-outline font-mono overflow-x-auto bg-surface-dim p-1.5">
                        ARGS: {JSON.stringify(entry.args)}
                      </div>
                    )}

                    <div className="text-parchment text-[11px] border-t border-outline-variant/20 pt-1">
                      RESULT: {entry.result}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
