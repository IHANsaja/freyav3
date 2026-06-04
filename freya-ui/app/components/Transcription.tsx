"use client";

import { useEffect, useRef } from "react";
import { TranscriptEntry } from "../hooks/useFreyaSocket";

interface TranscriptionProps {
  transcript: TranscriptEntry[];
  onClear: () => void;
}

export default function Transcription({ transcript, onClear }: TranscriptionProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  return (
    <div className="flex flex-col h-full bg-zinc-900 border border-zinc-700 rounded-2xl overflow-hidden">

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
        <h2 className="text-sm font-semibold text-zinc-200">Conversation</h2>
        <button
          onClick={onClear}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Clear
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
        {transcript.length === 0 ? (
          <p className="text-zinc-600 text-sm text-center mt-8">
            Start Freya and say something...
          </p>
        ) : (
          transcript.map((entry) => (
            <div
              key={entry.id}
              className={`flex flex-col gap-1 ${
                entry.speaker === "Ihan" ? "items-end" : "items-start"
              }`}
            >
              <span className="text-xs text-zinc-500">{entry.speaker}</span>
              <div
                className={`px-4 py-2 rounded-2xl text-sm max-w-[85%] leading-relaxed
                  ${
                    entry.speaker === "Ihan"
                      ? "bg-emerald-500/20 text-emerald-100 rounded-tr-sm"
                      : "bg-zinc-800 text-zinc-200 rounded-tl-sm"
                  }`}
              >
                {entry.text}
              </div>
              <span className="text-xs text-zinc-600">
                {entry.timestamp.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

    </div>
  );
}