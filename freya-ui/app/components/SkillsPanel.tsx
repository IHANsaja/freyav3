"use client";

import { useCallback, useEffect, useState } from "react";

interface SkillEntry {
    id: string;
    name: string;
    description: string;
    gate: string | null;
    enabled: boolean;
    version: string;
    tools: string[];
}

/** Skill catalog: every capability module, its tools, and enable toggles. */
export default function SkillsPanel() {
    const [skills, setSkills] = useState<SkillEntry[]>([]);
    const [note, setNote] = useState("");

    const load = useCallback(async () => {
        try {
            const res = await fetch("http://localhost:8000/skills");
            const data = await res.json();
            setSkills(data.skills ?? []);
        } catch (e) {
            console.error("skills load failed", e);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    const toggle = async (id: string) => {
        const res = await fetch(`http://localhost:8000/skills/${id}/toggle`, { method: "POST" });
        if (res.ok) {
            setNote("Change applies on next session start.");
            load();
        }
    };

    return (
        <div className="flex flex-col gap-1 max-h-52 overflow-y-auto">
            {skills.map((s) => (
                <div key={s.id} className="flex items-center gap-3 py-1.5 border-b border-outline-variant/15">
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                            <span className="text-[11px] font-semibold text-parchment">{s.name}</span>
                            <span className="text-[9px] font-mono text-outline">
                                {s.tools.length} tool{s.tools.length === 1 ? "" : "s"}
                            </span>
                        </div>
                        <p className="text-[10px] text-on-surface-variant truncate">{s.description}</p>
                    </div>
                    {s.gate ? (
                        <button
                            onClick={() => toggle(s.id)}
                            className={`px-3 py-1 rounded-full text-[9px] font-bold tracking-widest uppercase border transition-all flex-none ${
                                s.enabled
                                    ? "bg-primary-container text-parchment border-primary-container"
                                    : "text-outline border-outline-variant/40 hover:border-primary/50"
                            }`}
                        >
                            {s.enabled ? "On" : "Off"}
                        </button>
                    ) : (
                        <span className="text-[9px] font-mono uppercase tracking-widest text-outline/60 flex-none">
                            core
                        </span>
                    )}
                </div>
            ))}
            {note && (
                <p className="text-[9px] font-mono uppercase tracking-widest text-primary mt-1">{note}</p>
            )}
        </div>
    );
}
