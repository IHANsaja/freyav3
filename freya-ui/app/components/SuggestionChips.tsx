"use client";

import type { SuggestionPayload } from "../types/events";

interface SuggestionChipsProps {
    suggestions: SuggestionPayload[];
    onRespond: (id: string, accepted: boolean) => void;
}

const KIND_ICONS: Record<string, string> = {
    stuck: "◆",
    form: "▤",
    idle_return: "↩",
    followup: "◔",
};

/** Freya's proactive nudges — dismissible chips floating over the stage. */
export default function SuggestionChips({ suggestions, onRespond }: SuggestionChipsProps) {
    if (suggestions.length === 0) return null;
    return (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-30 flex flex-col gap-2 items-center pointer-events-none max-w-[520px] w-full px-4">
            {suggestions.map((s) => (
                <div
                    key={s.id}
                    className="pointer-events-auto flex items-center gap-3 px-4 py-2.5 bg-surface-container-low/85 border border-outline-variant/40 backdrop-blur-md animate-[projection-in_0.3s_ease-out]"
                    style={{ borderRadius: 0 }}
                >
                    <span className="text-primary text-xs">{KIND_ICONS[s.kind] ?? "◆"}</span>
                    <p className="text-xs text-parchment leading-snug">{s.text}</p>
                    <div className="flex items-center gap-2 ml-2">
                        <button
                            onClick={() => onRespond(s.id, true)}
                            className="px-3 py-1 rounded-full text-[10px] font-bold tracking-widest uppercase bg-primary-container text-parchment hover:bg-primary-container/90 transition-all"
                        >
                            Do it
                        </button>
                        <button
                            onClick={() => onRespond(s.id, false)}
                            className="px-2 py-1 text-[10px] font-mono tracking-widest uppercase text-outline hover:text-parchment transition-all"
                            title="Dismiss (Freya nudges less after dismissals)"
                        >
                            ✕
                        </button>
                    </div>
                </div>
            ))}
        </div>
    );
}
