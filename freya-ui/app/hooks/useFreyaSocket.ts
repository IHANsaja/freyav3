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
        liveText,
        toolLog,
        images,
        newsItems,
        config,
        activeMode,
        micPaused,
        memory,
        // Actions
        startFreya,
        stopFreya,
        setModel,
        setVoice,
        setMode,
        toggleListening,
        saveMemory,
        clearTranscript,
        clearToolLog,
    };
}
