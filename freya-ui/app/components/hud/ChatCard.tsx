"use client";

import { useEffect, useRef } from "react";
import type { TranscriptEntry } from "../../hooks/useFreyaSocket";
import HudCard from "./HudCard";

function time(d: Date): string {
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * The live conversation. Freya is voice-first, so this is a *readable record*
 * of what was actually said rather than a text input surface: every committed
 * turn, plus her current sentence as it streams in.
 *
 * Until now the transcript was collected by the socket hook but never shown
 * anywhere in the HUD — you could hear Freya but not review her.
 */
export default function ChatCard({
  transcript,
  liveText,
  className = "",
}: {
  transcript: TranscriptEntry[];
  liveText: string;
  className?: string;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  // Auto-follow the conversation, but only while the user is already at the
  // bottom — otherwise scrolling back to re-read gets yanked away mid-sentence.
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [transcript, liveText]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const empty = transcript.length === 0 && !liveText;

  return (
    <HudCard
      title="Conversation"
      className={className}
      bodyClassName="min-h-0"
      right={
        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
          {transcript.length}
        </span>
      }
    >
      <div
        ref={scroller}
        onScroll={onScroll}
        className="h-full min-h-0 overflow-y-auto pr-1 flex flex-col gap-2.5"
      >
        {empty && (
          <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
            Nothing said yet. Press start and talk — the conversation appears here.
          </p>
        )}

        {transcript.map((entry) => {
          const isFreya = entry.speaker === "Freya";
          return (
            <div key={entry.id} className="flex flex-col gap-0.5">
              <div className="flex items-baseline gap-2">
                <span
                  className="text-[9px] tracking-[0.2em] uppercase shrink-0"
                  style={{
                    fontFamily: "var(--font-ui)",
                    color: isFreya ? "var(--accent-red)" : "var(--text-secondary)",
                  }}
                >
                  {entry.speaker}
                </span>
                <span className="text-[9px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  {time(entry.timestamp)}
                </span>
              </div>
              <p
                className="text-[11px] leading-relaxed pl-0.5 border-l-2 pl-2"
                style={{
                  color: isFreya ? "var(--text-primary)" : "var(--text-secondary)",
                  borderColor: isFreya ? "var(--accent-red-dim)" : "var(--panel-border)",
                }}
              >
                {entry.text}
              </p>
            </div>
          );
        })}

        {/* Freya's current turn, still streaming. */}
        {liveText && (
          <div className="flex flex-col gap-0.5">
            <span
              className="text-[9px] tracking-[0.2em] uppercase"
              style={{ fontFamily: "var(--font-ui)", color: "var(--accent-red)" }}
            >
              Freya
            </span>
            <p
              className="text-[11px] leading-relaxed border-l-2 pl-2"
              style={{ color: "var(--text-primary)", borderColor: "var(--accent-red)" }}
            >
              {liveText}
              <span className="type-caret" aria-hidden />
            </p>
          </div>
        )}
      </div>
    </HudCard>
  );
}
