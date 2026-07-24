"use client";

import { useEffect, useState } from "react";
import type { PendingApproval } from "../types/events";

interface ApprovalPromptProps {
    approvals: PendingApproval[];
    onRespond: (id: string, approved: boolean) => void;
}

/** Countdown fraction (1 → 0) toward an action's expiry. */
function useCountdown(expiresAt: number, windowS = 120) {
    const [fraction, setFraction] = useState(1);
    useEffect(() => {
        const tick = () => {
            const remaining = expiresAt - Date.now() / 1000;
            setFraction(Math.max(0, Math.min(1, remaining / windowS)));
        };
        tick();
        const id = setInterval(tick, 1000);
        return () => clearInterval(id);
    }, [expiresAt, windowS]);
    return fraction;
}

function ApprovalCard({
    action,
    onRespond,
}: {
    action: PendingApproval;
    onRespond: (id: string, approved: boolean) => void;
}) {
    const fraction = useCountdown(action.expiresAt);
    const fromMission = action.source.startsWith("mission");

    return (
        <div
            className="pointer-events-auto relative w-full px-6 py-4 rounded-2xl animate-[projection-in_0.35s_ease-out]"
            style={{
                background:
                    "linear-gradient(135deg, rgba(20,8,8,0.85) 0%, rgba(40,10,10,0.8) 100%)",
                backdropFilter: "blur(18px) saturate(140%)",
                WebkitBackdropFilter: "blur(18px) saturate(140%)",
                border: "1px solid rgba(15,156,110,0.45)",
                boxShadow:
                    "0 8px 40px rgba(0,0,0,0.7), 0 0 40px rgba(15,156,110,0.15)",
            }}
        >
            <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse shadow-[0_0_8px] shadow-primary" />
                <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-primary">
                    Approval required
                </span>
                <span className="text-[10px] font-mono tracking-widest uppercase text-outline ml-auto">
                    {fromMission ? "MISSION" : action.tool}
                </span>
            </div>

            <p className="text-sm text-parchment leading-relaxed mb-1">
                Freya wants to <span className="font-semibold">{action.summary}</span>
            </p>
            {action.argsPreview && (
                <p className="text-[11px] font-mono text-outline truncate mb-3">
                    {action.argsPreview}
                </p>
            )}

            <div className="flex items-center gap-3">
                <button
                    onClick={() => onRespond(action.id, true)}
                    className="px-6 py-2 rounded-full text-[11px] font-bold tracking-widest uppercase bg-primary-container text-parchment hover:bg-primary-container/90 hover:shadow-[0_0_20px_rgba(15,156,110,0.5)] transition-all duration-300"
                >
                    Approve
                </button>
                <button
                    onClick={() => onRespond(action.id, false)}
                    className="px-6 py-2 rounded-full text-[11px] font-bold tracking-widest uppercase border border-outline-variant/40 text-outline hover:border-primary/60 hover:text-parchment transition-all duration-300"
                >
                    Deny
                </button>
                <span className="text-[10px] font-mono text-outline ml-auto">
                    say “yes” or “no” works too
                </span>
            </div>

            {/* Expiry countdown */}
            <div className="absolute bottom-0 left-4 right-4 h-px overflow-hidden rounded-full">
                <div
                    className="h-full bg-primary/70 transition-[width] duration-1000 ease-linear"
                    style={{ width: `${fraction * 100}%` }}
                />
            </div>
        </div>
    );
}

export default function ApprovalPrompt({ approvals, onRespond }: ApprovalPromptProps) {
    if (approvals.length === 0) return null;
    return (
        <div className="absolute bottom-56 left-1/2 -translate-x-1/2 w-full max-w-[480px] px-4 z-40 pointer-events-none flex flex-col gap-3">
            {approvals.map((a) => (
                <ApprovalCard key={a.id} action={a} onRespond={onRespond} />
            ))}
        </div>
    );
}
