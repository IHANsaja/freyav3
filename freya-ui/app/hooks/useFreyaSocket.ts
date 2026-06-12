import { useEffect, useRef, useState, useCallback } from "react";

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
    const [toolLog, setToolLog] = useState<ToolEntry[]>([]);
    const [config, setConfig] = useState<FreyaConfig | null>(null);
    const [activeMode, setActiveMode] = useState<string>("default");
    const [memory, setMemory] = useState<string>("");
    const [connected, setConnected] = useState(false);

    // ── Fetch initial config and memory ──
    useEffect(() => {
        fetch("http://localhost:8000/config")
            .then((r) => r.json())
            .then((cfg: FreyaConfig) => {
                setConfig(cfg);
                if (cfg.active_mode) setActiveMode(cfg.active_mode);
            })
            .catch(console.error);

        fetch("http://localhost:8000/memory")
            .then((r) => r.json())
            .then((d) => setMemory(d.content))
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
                } else if (msg.type === "transcript") {
                    if (msg.speaker === "Freya") {
                        // Buffer Freya's words
                        freyaBuffer.current += " " + msg.text;
                    } else {
                        // Flush any pending Freya buffer first
                        flushFreyaBuffer();
                        // Then add Ihan's message
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

    const saveMemory = useCallback(async (content: string) => {
        await fetch("http://localhost:8000/memory", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
        });
        setMemory(content);
    }, []);

    const clearTranscript = useCallback(() => setTranscript([]), []);
    const clearToolLog = useCallback(() => setToolLog([]), []);

    return {
        // State
        state,
        connected,
        transcript,
        toolLog,
        config,
        activeMode,
        memory,
        // Actions
        startFreya,
        stopFreya,
        setModel,
        setVoice,
        setMode,
        saveMemory,
        clearTranscript,
        clearToolLog,
    };
}
