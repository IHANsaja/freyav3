"use client";

import { useEffect, useRef } from "react";
import { TranscriptEntry, ToolEntry, FreyaState } from "../hooks/useFreyaSocket";
import Typewriter from "./Typewriter";
import VisualCards from "./VisualCards";

interface LivePanelProps {
  state: FreyaState;
  transcript: TranscriptEntry[];
  liveText: string;
  toolLog: ToolEntry[];
  onClear: () => void;
}

/**
 * The right-hand live panel (replaces the old ArchivalPanel). Two stacked regions:
 *   1. Conversation — committed lines, plus Freya's CURRENT line typing out live.
 *   2. Visuals — contextual cards that appear as Freya acts (news, weather, …).
 */
export default function LivePanel({
  state,
  transcript,
  liveText,
  toolLog,
  onClear,
}: LivePanelProps) {
  const convoEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    convoEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript, liveText]);

  const speaking = state === "speaking" && liveText.length > 0;

  return (
    <div className="w-full h-full flex flex-col bg-surface border-l border-outline-variant/30 text-parchment">
      {/* Header */}
      <div className="px-6 py-5 border-b border-outline-variant/20 flex items-center justify-between">
        <div className="flex flex-col gap-0.5">
          <h2 className="text-base font-bold tracking-widest text-parchment uppercase">LIVE FEED</h2>
          <span className="text-[10px] font-semibold text-outline tracking-widest font-mono uppercase">
            {state === "speaking"
              ? "● FREYA SPEAKING"
              : state === "listening"
              ? "● LISTENING"
              : state === "interrupted"
              ? "● YIELDING"
              : "○ STANDBY"}
          </span>
        </div>
        <button
          onClick={onClear}
          className="text-[9px] text-outline hover:text-parchment border border-outline-variant/30 px-2 py-0.5 transition-colors uppercase tracking-wider"
          style={{ borderRadius: "0px" }}
        >
          Clear
        </button>
      </div>

      {/* Conversation (typing) */}
      <div className="flex flex-col gap-3 px-6 py-4 overflow-y-auto max-h-[42%] min-h-[120px] border-b border-outline-variant/20 leading-relaxed">
        {transcript.length === 0 && !speaking ? (
          <div className="text-outline-variant italic uppercase text-xs tracking-wider mt-1">
            No transmission active. Standing by…
          </div>
        ) : (
          transcript.map((entry) => (
            <div key={entry.id} className="flex flex-col gap-0.5 text-[13px]">
              <span
                className={`text-[10px] font-bold uppercase tracking-widest ${
                  entry.speaker === "Ihan" ? "text-outline" : "text-primary"
                }`}
              >
                {entry.speaker}
              </span>
              <span className="text-parchment">{entry.text}</span>
            </div>
          ))
        )}

        {/* The live, currently-spoken line types out in real time */}
        {speaking && (
          <div className="flex flex-col gap-0.5 text-[13px]">
            <span className="text-[10px] font-bold uppercase tracking-widest text-primary">
              Freya
            </span>
            <Typewriter text={liveText} className="text-parchment" />
          </div>
        )}
        <div ref={convoEnd} />
      </div>

      {/* Visual cards */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4">
        <div className="text-[10px] font-bold uppercase tracking-widest text-outline mb-3">
          Context
        </div>
        <VisualCards toolLog={toolLog} />
      </div>
    </div>
  );
}
