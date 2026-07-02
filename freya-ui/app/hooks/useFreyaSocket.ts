import { useEffect, useRef, useState, useCallback } from "react";
import type {
    ApprovalPayload,
    AvatarIntentPayload,
    ContextPayload,
    MissionEventPayload,
    MissionPayload,
    PendingApproval,
    PersonaPayload,
    SuggestionPayload,
} from "../types/events";

export type AvatarIntent = AvatarIntentPayload & { seq: number };

// ── Types ──
export type FreyaState = "idle" | "listening" | "speaking" | "interrupted";

export interface TranscriptEntry {
    id: number;
    speaker: "Ihan" | "Freya";
    text: string;
    timestamp: Date;
}

export interface ToolEntry {
    id: number;
    name: string;
    args: Record<string, unknown>;
    result: string;
    timestamp: Date;
}

export interface ImageEntry {
    id: number;
    data: string;   // base64 JPEG (no data: prefix)
    label: string;
    timestamp: Date;
}

export interface NewsItem {
    id: number;
    title: string;
    source: string;
    image: string | null;   // scraped article photo, fills in asynchronously
    logo: string | null;    // source logo, available immediately
    timestamp: Date;
}

export interface FreyaMode {
    label: string;
}

export interface FreyaConfig {
    active_model: string;
    active_voice: string;
    models: { id: string; label: string }[];
    voices: string[];
    modes?: Record<string, FreyaMode>;
    active_mode?: string;
}

// ── Hook ──
export function useFreyaSocket() {
    const ws = useRef<WebSocket | null>(null);
    const counter = useRef(0);
    const freyaBuffer = useRef<string>("");

    const [state, setState] = useState<FreyaState>("idle");
    const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
    const [liveText, setLiveText] = useState<string>(""); // Freya's words as she speaks
    const [toolLog, setToolLog] = useState<ToolEntry[]>([]);
    const [images, setImages] = useState<ImageEntry[]>([]);
    const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
    const [config, setConfig] = useState<FreyaConfig | null>(null);
    const [activeMode, setActiveMode] = useState<string>("default");
    const [micPaused, setMicPaused] = useState(false);
    const [memoryVersion, setMemoryVersion] = useState(0);
    const [connected, setConnected] = useState(false);
    const [approvals, setApprovals] = useState<PendingApproval[]>([]);
    const [missions, setMissions] = useState<Record<string, MissionPayload>>({});
    const [avatarIntent, setAvatarIntent] = useState<AvatarIntent | null>(null);
    const avatarSeq = useRef(0);
    const [suggestions, setSuggestions] = useState<SuggestionPayload[]>([]);
    const [contextInfo, setContextInfo] = useState<ContextPayload | null>(null);
    const [persona, setPersona] = useState<PersonaPayload | null>(null);

    // ── Fetch initial config ──
    useEffect(() => {
        fetch("http://localhost:8000/config")
            .then((r) => r.json())
            .then((cfg: FreyaConfig) => {
                setConfig(cfg);
                if (cfg.active_mode) setActiveMode(cfg.active_mode);
            })
            .catch(console.error);
    }, []);

    // ── WebSocket connection ──
    useEffect(() => {
        const connect = () => {
            const socket = new WebSocket("ws://localhost:8000/ws");

            socket.onopen = () => {
                setConnected(true);
                console.log("Freya WebSocket connected");
            };

            socket.onclose = () => {
                setConnected(false);
                console.log("Freya WebSocket disconnected, retrying in 2s...");
                setTimeout(connect, 2000); // auto-reconnect
            };

            socket.onerror = (e) => {
                console.error("WebSocket error", e);
            };

            const flushFreyaBuffer = () => {
                const freyaText = freyaBuffer.current.trim();
                if (freyaText) {
                    setTranscript((prev) => [
                        ...prev,
                        {
                            id: counter.current++,
                            speaker: "Freya",
                            text: freyaText,
                            timestamp: new Date(),
                        },
                    ]);
                    freyaBuffer.current = "";
                }
                setLiveText(""); // turn done — stop the live typing line
            };

            socket.onmessage = (event) => {
                const msg = JSON.parse(event.data);

                if (msg.type === "state") {
                    setState(msg.value as FreyaState);
                    // Turn complete or barge-in → flush Freya's buffered words
                    if (msg.value === "listening" || msg.value === "interrupted") {
                        flushFreyaBuffer();
                    }
                } else if (msg.type === "mode") {
                    setActiveMode(msg.value);
                } else if (msg.type === "mic") {
                    setMicPaused(!!msg.paused);
                } else if (msg.type === "speech") {
                    // Live streaming of Freya's words → center-scene typing caption
                    freyaBuffer.current += " " + msg.text;
                    setLiveText(freyaBuffer.current.trim());
                } else if (msg.type === "transcript") {
                    if (msg.speaker === "Ihan") {
                        // User's turn captured → commit Freya's line + clear caption
                        flushFreyaBuffer();
                        setTranscript((prev) => [
                            ...prev,
                            {
                                id: counter.current++,
                                speaker: msg.speaker,
                                text: msg.text,
                                timestamp: new Date(),
                            },
                        ]);
                    }
                    // Freya's full transcript ignored here — already streamed via "speech".
                } else if (msg.type === "tool") {
                    setToolLog((prev) => [
                        ...prev,
                        {
                            id: counter.current++,
                            name: msg.name,
                            args: msg.args,
                            result: msg.result,
                            timestamp: new Date(),
                        },
                    ]);
                } else if (msg.type === "image") {
                    // A new image Freya received (e.g. a screen capture) → show on the canvas.
                    setImages((prev) => [
                        ...prev,
                        {
                            id: counter.current++,
                            data: msg.data,
                            label: msg.label || "Image",
                            timestamp: new Date(),
                        },
                    ].slice(-6));
                } else if (msg.type === "news") {
                    // Structured world-news headlines → dynamic scene projections.
                    const now = new Date();
                    const incoming: NewsItem[] = (msg.items || []).map(
                        (it: { id: number; title: string; source: string; image: string | null; logo: string | null }) => ({
                            id: it.id,
                            title: it.title,
                            source: it.source,
                            image: it.image ?? null,
                            logo: it.logo ?? null,
                            timestamp: now,
                        })
                    );
                    const ids = new Set(incoming.map((i) => i.id));
                    setNewsItems((prev) => [...incoming, ...prev.filter((p) => !ids.has(p.id))].slice(0, 8));
                } else if (msg.type === "news_image") {
                    // A scraped image arrived for a headline → attach it.
                    setNewsItems((prev) =>
                        prev.map((it) => (it.id === msg.id ? { ...it, image: msg.image } : it))
                    );
                } else if (msg.type === "persona") {
                    const p = msg.payload as PersonaPayload;
                    setPersona(p);
                    // Persona idle pose rides the avatar intent channel.
                    if (p.theme?.avatarIdle) {
                        setAvatarIntent({
                            intent: "idle",
                            name: p.theme.avatarIdle,
                            seq: ++avatarSeq.current,
                        });
                    }
                } else if (msg.type === "memory_changed") {
                    setMemoryVersion((v) => v + 1);
                } else if (msg.type === "suggestion") {
                    const p = msg.payload as SuggestionPayload;
                    if (p.event === "created") {
                        setSuggestions((prev) =>
                            prev.some((s) => s.id === p.id) ? prev : [...prev.slice(-2), p]
                        );
                    } else {
                        setSuggestions((prev) => prev.filter((s) => s.id !== p.id));
                    }
                } else if (msg.type === "context") {
                    setContextInfo(msg.payload as ContextPayload);
                } else if (msg.type === "avatar") {
                    setAvatarIntent({
                        ...(msg.payload as AvatarIntentPayload),
                        seq: ++avatarSeq.current,
                    });
                } else if (msg.type === "mission") {
                    const p = msg.payload as MissionEventPayload;
                    setMissions((prev) => ({ ...prev, [p.mission.id]: p.mission }));
                } else if (msg.type === "approval") {
                    const p = msg.payload as ApprovalPayload;
                    if (p.event === "requested") {
                        const { event: _event, ...action } = p;
                        setApprovals((prev) =>
                            prev.some((a) => a.id === action.id) ? prev : [...prev, action]
                        );
                    } else {
                        setApprovals((prev) => prev.filter((a) => a.id !== p.id));
                    }
                } else if (["agent", "browser", "schedule", "ambient", "mcp"].includes(msg.type)) {
                    // Superpower status events → surface them in the tool feed.
                    const { type, ...rest } = msg;
                    setToolLog((prev) => [
                        ...prev,
                        {
                            id: counter.current++,
                            name: `⚡ ${type}`,
                            args: rest,
                            result: rest.status || rest.task || "",
                            timestamp: new Date(),
                        },
                    ]);
                }
            };

            ws.current = socket;
        };

        connect();
        return () => ws.current?.close();
    }, []);

    // ── Actions ──
    const send = useCallback((msg: object) => {
        if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify(msg));
        }
    }, []);

    const startFreya = useCallback(() => send({ type: "start" }), [send]);
    const stopFreya = useCallback(() => send({ type: "stop" }), [send]);

    const setModel = useCallback((model: string) => {
        send({ type: "set_model", model });
        setConfig((prev) => prev ? { ...prev, active_model: model } : prev);
    }, [send]);

    const setVoice = useCallback((voice: string) => {
        send({ type: "set_voice", voice });
        setConfig((prev) => prev ? { ...prev, active_voice: voice } : prev);
    }, [send]);

    const setMode = useCallback((mode: string) => {
        send({ type: "set_mode", mode });
        setActiveMode(mode); // optimistic; server re-broadcasts on success
    }, [send]);

    const toggleListening = useCallback(() => {
        const next = !micPaused;
        send({ type: "set_listening", paused: next });
        setMicPaused(next); // optimistic; server confirms via "mic"
    }, [send, micPaused]);

    const respondApproval = useCallback((id: string, approved: boolean) => {
        send({ type: "approval_response", id, approved });
        setApprovals((prev) => prev.filter((a) => a.id !== id)); // optimistic
    }, [send]);

    const cancelMission = useCallback((id: string) => {
        send({ type: "mission_command", action: "cancel", id });
    }, [send]);

    const respondSuggestion = useCallback((id: string, accepted: boolean) => {
        send({ type: "suggestion_response", id, accepted });
        setSuggestions((prev) => prev.filter((s) => s.id !== id)); // optimistic
    }, [send]);

    // Most recent mission that is still running, else the most recent overall.
    const missionList = Object.values(missions);
    const activeMission =
        missionList
            .filter((m) => !["done", "failed", "cancelled"].includes(m.status))
            .at(-1) ?? missionList.at(-1) ?? null;

    const clearTranscript = useCallback(() => setTranscript([]), []);
    const clearToolLog = useCallback(() => setToolLog([]), []);

    return {
        // State
        state,
        connected,
        transcript,
        liveText,
        toolLog,
        images,
        newsItems,
        config,
        activeMode,
        micPaused,
        memoryVersion,
        approvals,
        missions,
        activeMission,
        avatarIntent,
        suggestions,
        contextInfo,
        persona,
        // Actions
        startFreya,
        stopFreya,
        setModel,
        setVoice,
        setMode,
        toggleListening,
        respondApproval,
        cancelMission,
        respondSuggestion,
        clearTranscript,
        clearToolLog,
    };
}
