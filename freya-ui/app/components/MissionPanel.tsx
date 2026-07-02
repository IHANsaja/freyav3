"use client";

import { useState } from "react";
import type { MissionPayload, MissionStepPayload } from "../types/events";

interface MissionPanelProps {
    mission: MissionPayload | null;
    onCancel: (id: string) => void;
}

const MISSION_STATUS_LABEL: Record<string, string> = {
    planning: "PLANNING",
    running: "EXECUTING",
    awaiting_approval: "AWAITING APPROVAL",
    verifying: "VERIFYING",
    done: "COMPLETE",
    failed: "FAILED",
    cancelled: "CANCELLED",
};

function StepGlyph({ status }: { status: MissionStepPayload["status"] }) {
    switch (status) {
        case "done":
            return <span className="text-emerald-400">✓</span>;
        case "failed":
            return <span className="text-secondary">✕</span>;
        case "skipped":
            return <span className="text-outline">–</span>;
        case "running":
        case "verifying":
            return (
                <span className="inline-block w-2.5 h-2.5 rounded-full border border-primary border-t-transparent animate-spin" />
            );
        case "awaiting_approval":
            return <span className="text-primary animate-pulse">⏸</span>;
        default:
            return <span className="text-outline/60">○</span>;
    }
}

export default function MissionPanel({ mission, onCancel }: MissionPanelProps) {
    const [collapsed, setCollapsed] = useState(false);

    if (!mission) return null;

    const finished = ["done", "failed", "cancelled"].includes(mission.status);
    const doneCount = mission.steps.filter((s) => s.status === "done").length;
    const progress = mission.steps.length > 0 ? doneCount / mission.steps.length : 0;
    const activeStep = mission.steps.find((s) =>
        ["running", "verifying", "awaiting_approval"].includes(s.status)
    );

    // Slim chip when collapsed (or when the mission is long finished).
    if (collapsed) {
        return (
            <button
                onClick={() => setCollapsed(false)}
                className="absolute top-6 right-6 z-30 flex items-center gap-2 px-4 py-2 bg-surface-container-low/80 border border-outline-variant/30 text-[10px] font-mono tracking-widest uppercase text-outline hover:border-primary/50 hover:text-parchment transition-all backdrop-blur-md"
                style={{ borderRadius: 0 }}
            >
                <span
                    className={`w-1.5 h-1.5 rounded-full ${
                        finished ? "bg-outline" : "bg-primary animate-pulse"
                    }`}
                />
                MISSION {MISSION_STATUS_LABEL[mission.status] ?? mission.status}
            </button>
        );
    }

    return (
        <aside
            className="absolute top-6 right-6 bottom-32 z-30 w-[340px] flex flex-col bg-surface-container-lowest/85 border border-outline-variant/30 backdrop-blur-md overflow-hidden"
            style={{ borderRadius: 0 }}
        >
            {/* Header */}
            <div className="px-5 pt-4 pb-3 border-b border-outline-variant/20">
                <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-primary">
                        Mission · {mission.id}
                    </span>
                    <div className="flex items-center gap-2">
                        <span
                            className={`text-[10px] font-mono tracking-widest uppercase ${
                                mission.status === "awaiting_approval"
                                    ? "text-primary animate-pulse"
                                    : finished
                                    ? "text-outline"
                                    : "text-parchment"
                            }`}
                        >
                            {MISSION_STATUS_LABEL[mission.status] ?? mission.status}
                        </span>
                        <button
                            onClick={() => setCollapsed(true)}
                            className="text-outline hover:text-parchment text-xs px-1"
                            title="Collapse"
                        >
                            —
                        </button>
                    </div>
                </div>
                <p className="text-sm text-parchment leading-snug">{mission.goal}</p>

                {/* Progress bar */}
                <div className="mt-3 h-px bg-outline-variant/30 overflow-hidden">
                    <div
                        className="h-full bg-primary transition-[width] duration-700 ease-out"
                        style={{ width: `${progress * 100}%` }}
                    />
                </div>
            </div>

            {/* Steps */}
            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-3">
                {mission.steps.length === 0 && (
                    <p className="text-[11px] font-mono text-outline tracking-wider uppercase animate-pulse">
                        Decomposing goal into steps…
                    </p>
                )}
                {mission.steps.map((step) => (
                    <div key={step.id} className="flex gap-3">
                        <div className="w-4 pt-0.5 text-xs flex-none text-center">
                            <StepGlyph status={step.status} />
                        </div>
                        <div className="min-w-0">
                            <p
                                className={`text-xs leading-snug ${
                                    step.status === "done"
                                        ? "text-outline"
                                        : step.status === "failed"
                                        ? "text-secondary"
                                        : "text-parchment"
                                }`}
                            >
                                {step.id}. {step.title}
                                {step.sensitive && (
                                    <span className="ml-2 text-[9px] font-mono uppercase tracking-widest text-primary/80">
                                        sensitive
                                    </span>
                                )}
                            </p>
                            {step.status === "awaiting_approval" && (
                                <p className="text-[10px] font-mono text-primary tracking-wider uppercase mt-0.5 animate-pulse">
                                    waiting for your approval
                                </p>
                            )}
                            {step.verification && step.status !== "done" && (
                                <p className="text-[10px] text-outline mt-0.5 line-clamp-2">
                                    {step.verification}
                                </p>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {/* Active step / report footer */}
            <div className="px-5 py-3 border-t border-outline-variant/20">
                {mission.report ? (
                    <p className="text-[11px] text-outline leading-relaxed line-clamp-4">
                        {mission.report}
                    </p>
                ) : activeStep ? (
                    <p className="text-[10px] font-mono text-outline tracking-wider uppercase truncate">
                        ▸ {activeStep.title}
                    </p>
                ) : (
                    <p className="text-[10px] font-mono text-outline tracking-wider uppercase">
                        {finished ? "mission closed" : "standing by"}
                    </p>
                )}
                {!finished && (
                    <button
                        onClick={() => onCancel(mission.id)}
                        className="mt-2 px-4 py-1.5 rounded-full text-[10px] font-bold tracking-widest uppercase border border-outline-variant/40 text-outline hover:border-secondary hover:text-secondary transition-all"
                    >
                        Cancel mission
                    </button>
                )}
            </div>
        </aside>
    );
}
