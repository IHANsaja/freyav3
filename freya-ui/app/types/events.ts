// TypeScript mirror of the backend WebSocket event schema (core/events.py).
// New event families arrive as { type, payload: {...} }; legacy families
// (state, transcript, tool, news, ...) keep their original flat shape.

// ── Approvals ──
export interface PendingApproval {
    id: string;
    summary: string;
    tool: string;
    argsPreview: string;
    source: string; // "live" | "mission:<id>" | "suggestion"
    expiresAt: number; // unix seconds
}

export type ApprovalPayload =
    | ({ event: "requested" } & PendingApproval)
    | { event: "resolved"; id: string; approved: boolean; via: "voice" | "ui" | "timeout" };

// ── Missions ──
export type MissionStepStatus =
    | "pending" | "running" | "verifying" | "awaiting_approval"
    | "done" | "failed" | "skipped";

export interface MissionStepPayload {
    outcome?: "success" | "failed" | "exhausted" | "denied" | "verification_error" | "timeout" | "cancelled";
    evidence?: string[];
    id: number;
    title: string;
    detail: string;
    status: MissionStepStatus;
    sensitive: boolean;
    result: string | null;
    verification: string | null;
}

export interface TradingEventPayload {
    session_id: string;
    sequence: number;
    revision: number;
    event: "changed" | "analysis";
}

export type MissionStatus =
    | "planning" | "running" | "awaiting_approval" | "verifying"
    | "done" | "failed" | "cancelled";

export interface MissionPayload {
    usage?: { requests: number; tokens: number; models: Record<string, number> };
    id: string;
    goal: string;
    status: MissionStatus;
    currentStep: number;
    report: string | null;
    steps: MissionStepPayload[];
}

export interface MissionEventPayload {
    event: "created" | "plan" | "step" | "status" | "report";
    mission: MissionPayload;
}

// ── Avatar ──
export type AvatarIntentKind = "expression" | "gesture" | "idle" | "emphasis" | "state";

export interface AvatarIntentPayload {
    intent: AvatarIntentKind;
    name: string;
    intensity?: number;
    durationMs?: number;
}

// ── Proactive suggestions ──
export type SuggestionKind = "stuck" | "form" | "idle_return" | "followup";

export interface SuggestionPayload {
    event: "created" | "resolved";
    id: string;
    text: string;
    kind: SuggestionKind;
}

// ── Context awareness ──
export interface ContextPayload {
    app: string;
    title: string;
    idleS: number;
}

// ── Info cards (retrieved text/images Freya puts on screen) ──
// Legacy-shaped event: arrives flat as { type: "card", ... }. `dashboard` and
// `popup` say which surfaces the card is meant for — the desktop popup layer
// lives in the Python process, so the dashboard simply ignores popup-only cards.
export interface CardEventPayload {
    title: string;
    body: string;
    source: string;
    image: string | null;   // base64 JPEG, no data: prefix
    url: string | null;
    durationMs?: number;
    dashboard?: boolean;
    popup?: boolean;
}

// ── Persona / mode theming ──
export interface PersonaPayload {
    mode: string;
    voice: string;
    theme: {
        accent: string;
        glow: number;
        coreParams?: Record<string, number>;
        avatarIdle?: string; // standing | seated | attentive
    };
}
