import { useEffect, useRef, useState, useCallback } from "react";
import type {
    ApprovalPayload,
    AvatarIntentPayload,
    CardEventPayload,
    ContextPayload,
    MissionEventPayload,
    MissionPayload,
    PendingApproval,
    PersonaPayload,
    SuggestionPayload,
} from "../types/events";

export type AvatarIntent = AvatarIntentPayload & { seq: number };

// ── Types ──
export type FreyaState = "idle" | "listening" | "speaking" | "interrupted" | "thinking";

export interface TranscriptEntry {
    id: number;
    speaker: "User" | "Freya";
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

/** A piece of information Freya retrieved (usually from the web) and chose to put
 *  on screen: a headline, a few sentences, an optional photo, a source. */
export interface InfoCard {
    id: number;
    title: string;
    body: string;
    source: string;
    image: string | null;   // base64 JPEG (no data: prefix)
    url: string | null;
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

export interface AudioDevice {
    index: number;
    name: string;
    /** The device Windows is currently using. */
    default?: boolean;
}

/** A background worker Freya has running: a sub-agent (researcher / coder /
 *  operator) or the browser operator. Mirrors GET /agents. */
export interface AgentJob {
    id: string;
    kind: string;            // researcher | coder | operator | browser
    task: string;
    status: string;          // started | working | running | done
    step?: string | null;    // the tool it is executing right now
    startedAt?: number | null; // unix seconds
    result?: string | null;
}

/** Real session telemetry (GET /status + the `session` broadcast). Replaces the
 *  HUD's former hardcoded session id and fabricated status rows. */
export interface SessionInfo {
    running: boolean;
    startedAt: number | null;
    model: string;
    voice: string;
    mode: string;
    tools: number;
    micPaused: boolean;
    clients: number;
}

/** A problem on the dashboard ↔ backend link: the WebSocket dropping, the
 *  /status ping failing, or the voice session reporting a connection error. */
export interface LinkError {
    id: number;
    source: "socket" | "ping" | "session";
    message: string;
    /** What to check to fix it. */
    hint?: string;
    /** How many times in a row it has happened. */
    count: number;
    firstSeen: Date;
    timestamp: Date;
}

/** Live statistics about the dashboard ↔ server.py link. */
export interface LinkStats {
    /** Last 30 pings, oldest first; null = no reply. */
    pingHistory: (number | null)[];
    /** Unix ms when the current socket opened; null while closed. */
    socketOpenedAt: number | null;
    /** Reconnect attempts since the socket last opened. */
    reconnectAttempts: number;
    /** Total socket (re)connects since page load. */
    connects: number;
    messagesReceived: number;
    lastMessageAt: number | null;
    lastClose: { code: number; reason: string; at: number } | null;
}

/** Plain-English meaning of WebSocket close codes. */
export const CLOSE_CODES: Record<number, string> = {
    1000: "Normal closure",
    1001: "Server going away (shutdown or restart)",
    1006: "Abnormal closure: no close frame. The server is down or unreachable",
    1011: "Server hit an internal error",
    1012: "Server restarting",
    1013: "Server overloaded: this client was too slow to keep up",
};

export interface FreyaConfig {
    active_model: string;
    active_voice: string;
    models: { id: string; label: string }[];
    voices: string[];
    input_device_index?: number | null;
    output_device_index?: number | null;
    modes?: Record<string, FreyaMode>;
    active_mode?: string;
}

// ── Hook ──
export function useFreyaSocketConnection() {
    const ws = useRef<WebSocket | null>(null);
    const counter = useRef(0);
    const freyaBuffer = useRef<string>("");

    const [state, setState] = useState<FreyaState>("idle");
    const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
    const [liveText, setLiveText] = useState<string>(""); // Freyja's words as she speaks
    const [toolLog, setToolLog] = useState<ToolEntry[]>([]);
    const [images, setImages] = useState<ImageEntry[]>([]);
    const [cards, setCards] = useState<InfoCard[]>([]);
    const [newsItems, setNewsItems] = useState<NewsItem[]>([]);
    const [config, setConfig] = useState<FreyaConfig | null>(null);
    const [audioDevices, setAudioDevices] = useState<{ input: AudioDevice[]; output: AudioDevice[] }>({
        input: [],
        output: [],
    });
    const [agents, setAgents] = useState<AgentJob[]>([]);
    const [session, setSession] = useState<SessionInfo | null>(null);
    const [activeMode, setActiveMode] = useState<string>("default");
    const [micPaused, setMicPaused] = useState(false);
    const [memoryVersion, setMemoryVersion] = useState(0);
    const [connected, setConnected] = useState(false);
    const [approvals, setApprovals] = useState<PendingApproval[]>([]);
    const [missions, setMissions] = useState<Record<string, MissionPayload>>({});
    const [avatarIntent, setAvatarIntent] = useState<AvatarIntent | null>(null);
    const avatarSeq = useRef(0);
    const [orbGestureEvent, setOrbGestureEvent] = useState<{ gesture: string; seq: number } | null>(null);
    const orbGestureSeq = useRef(0);
    const [suggestions, setSuggestions] = useState<SuggestionPayload[]>([]);
    const [contextInfo, setContextInfo] = useState<ContextPayload | null>(null);
    const [persona, setPersona] = useState<PersonaPayload | null>(null);
    const [linkErrors, setLinkErrors] = useState<LinkError[]>([]);
    const [pingMs, setPingMs] = useState<number | null>(null);
    const linkErrorSeq = useRef(0);
    const [linkStats, setLinkStats] = useState<LinkStats>({
        pingHistory: [], socketOpenedAt: null, reconnectAttempts: 0, connects: 0,
        messagesReceived: 0, lastMessageAt: null, lastClose: null,
    });
    // Message counting is batched: a state update per frame would re-render
    // the whole dashboard on every audio-level tick.
    const msgCounter = useRef({ n: 0, last: null as number | null });
    useEffect(() => {
        const id = setInterval(() => {
            const { n, last } = msgCounter.current;
            setLinkStats((p) => (p.messagesReceived === n ? p : { ...p, messagesReceived: n, lastMessageAt: last }));
        }, 1000);
        return () => clearInterval(id);
    }, []);

    // Consecutive repeats of the same error (a backend that stays down fails
    // every retry) bump the timestamp instead of flooding the list.
    const pushLinkError = useCallback((source: LinkError["source"], message: string, hint?: string) => {
        setLinkErrors((prev) => {
            const now = new Date();
            const last = prev.at(-1);
            if (last && last.source === source && last.message === message) {
                return [...prev.slice(0, -1), { ...last, count: last.count + 1, timestamp: now }];
            }
            return [...prev, { id: linkErrorSeq.current++, source, message, hint, count: 1, firstSeen: now, timestamp: now }].slice(-20);
        });
    }, []);
    const clearLinkErrors = useCallback(() => setLinkErrors([]), []);

    // ── Ping: round-trip to /status every 5 s ──
    useEffect(() => {
        let disposed = false;
        const ping = async () => {
            const t0 = performance.now();
            try {
                const res = await fetch("http://localhost:8000/status", {
                    cache: "no-store",
                    signal: AbortSignal.timeout(3000),
                });
                if (disposed) return;
                if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
                const ms = Math.round(performance.now() - t0);
                setPingMs(ms);
                setLinkStats((p) => ({ ...p, pingHistory: [...p.pingHistory, ms].slice(-30) }));
            } catch (e) {
                if (disposed) return;
                setPingMs(null);
                setLinkStats((p) => ({ ...p, pingHistory: [...p.pingHistory, null].slice(-30) }));
                const timedOut = e instanceof DOMException && e.name === "TimeoutError";
                if (timedOut) {
                    pushLinkError("ping", "GET /status timed out after 3 s",
                        "server.py is running but not answering. Its event loop may be blocked by a slow tool or a hung audio call.");
                } else if (e instanceof TypeError) {
                    pushLinkError("ping", "GET /status failed: network error (connection refused)",
                        "server.py isn't reachable on localhost:8000. Start it, or check whether it crashed in its terminal.");
                } else {
                    pushLinkError("ping", `GET /status failed: ${e instanceof Error ? e.message : String(e)}`,
                        "The server answered with an error. Check the server.py log for a traceback.");
                }
            }
        };
        ping();
        const id = setInterval(ping, 5000);
        return () => { disposed = true; clearInterval(id); };
    }, [pushLinkError]);

    // ── Fetch initial config ──
    // Runs on mount AND on every socket (re)connect, so starting server.py after
    // the page is already open fills in the config, modes and audio devices on
    // its own — previously they stayed empty until a manual refresh.
    const loadBackendConfig = useCallback(() => {
        // A failure here just means the backend isn't up yet. That's an expected
        // state with a retry loop behind it, not a bug, so it's logged with
        // console.warn rather than console.error: the Next.js dev overlay counts
        // console.error as an issue and would bury real errors under a stack
        // trace on every reload. Same reasoning as socket.onerror below.
        fetch("http://localhost:8000/config")
            .then((r) => r.json())
            .then((cfg: FreyaConfig) => {
                setConfig(cfg);
                if (cfg.active_mode) setActiveMode(cfg.active_mode);
            })
            .catch(() => {
                console.warn("Freyja config unavailable — backend offline, will retry on reconnect.");
            });
        fetch("http://localhost:8000/audio/devices")
            .then((r) => r.json())
            .then((devices: { input: AudioDevice[]; output: AudioDevice[] }) => setAudioDevices(devices))
            .catch(() => {
                // Covered by the config warning above — don't log the same
                // outage twice per reload.
            });
        // Jobs already running before this tab opened: the WS events only
        // describe jobs that START while connected, so without this a reload
        // mid-task shows an empty agent list.
        fetch("http://localhost:8000/agents")
            .then((r) => r.json())
            .then((d: { agents: AgentJob[] }) =>
                // Merge, don't replace: the socket connects in parallel and
                // replays recent agent events, so a plain overwrite could drop
                // a job that arrived while this request was still in flight.
                // Live socket state wins per id; the fetch fills in the rest.
                setAgents((prev) => {
                    const seen = new Set(prev.map((a) => a.id));
                    return [...prev, ...(d.agents ?? []).filter((a) => !seen.has(a.id))];
                })
            )
            .catch(() => {});
        fetch("http://localhost:8000/status")
            .then((r) => r.json())
            .then((s: SessionInfo) => setSession(s))
            .catch(() => {});
    }, []);

    // Held in a ref so the socket effect below can call it without taking it as
    // a dependency — that effect must keep an empty dep array, or a changed
    // array size tears down and reopens the WebSocket on hot reload. No
    // reassignment needed: loadBackendConfig is useCallback([]), so the value
    // captured here stays correct for the component's whole lifetime.
    const loadConfigRef = useRef(loadBackendConfig);

    useEffect(() => {
        loadBackendConfig();
    }, [loadBackendConfig]);

    // ── Dashboard visibility → backend ──
    // Tells server.py whether this tab is actually being looked at (visible
    // and focused). While no tab is, Freya mirrors her replies and cards onto
    // desktop popups in the bottom-right corner instead.
    const reportVisibility = useCallback(() => {
        const watching = document.visibilityState === "visible" && document.hasFocus();
        if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify({ type: "dashboard_visibility", watching }));
        }
    }, []);
    useEffect(() => {
        const events = ["visibilitychange", "focus", "blur"] as const;
        const target = (e: string) => (e === "visibilitychange" ? document : window);
        events.forEach((e) => target(e).addEventListener(e, reportVisibility));
        return () => events.forEach((e) => target(e).removeEventListener(e, reportVisibility));
    }, [reportVisibility]);

    // ── WebSocket connection ──
    useEffect(() => {
        let disposed = false;
        let reconnectTimer: ReturnType<typeof setTimeout>;
        const connect = () => {
            if (disposed) return;
            const socket = new WebSocket("ws://localhost:8000/ws");

            socket.onopen = () => {
                setConnected(true);
                reportVisibility();
                setLinkStats((p) => ({ ...p, socketOpenedAt: Date.now(), reconnectAttempts: 0, connects: p.connects + 1 }));
                console.log("Freyja WebSocket connected");
                // The socket coming up is the signal that the REST endpoints are
                // live too — pull the config that failed while it was down.
                loadConfigRef.current();
            };

            socket.onclose = (ev) => {
                setConnected(false);
                setLinkStats((p) => ({
                    ...p,
                    socketOpenedAt: null,
                    reconnectAttempts: p.reconnectAttempts + 1,
                    lastClose: { code: ev.code, reason: ev.reason, at: Date.now() },
                }));
                if (!disposed) {
                    const meaning = CLOSE_CODES[ev.code] ?? "Unknown close code";
                    pushLinkError("socket",
                        `ws://localhost:8000/ws closed: code ${ev.code} (${meaning})${ev.reason ? `, reason "${ev.reason}"` : ""}. Retrying every 2 s`,
                        ev.code === 1013
                            ? "The tab fell behind the server's broadcast queue, often because the tab was in the background or busy."
                            : ev.code === 1006
                                ? "Check that server.py is running and nothing else is using port 8000."
                                : undefined);
                }
                console.log("Freyja backend offline (is server.py running?) — retrying in 2s...");
                reconnectTimer = setTimeout(connect, 2000); // auto-reconnect
            };

            // Expected while the backend is down (we retry via onclose) —
            // console.warn keeps it out of the Next.js dev-overlay issue count.
            socket.onerror = () => {
                console.warn("Freyja WebSocket connection failed — will retry.");
                pushLinkError("socket", "WebSocket handshake to ws://localhost:8000/ws failed",
                    "The browser couldn't open the socket. Usually the backend is down or still starting.");
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
                msgCounter.current.n++;
                msgCounter.current.last = Date.now();
                // A malformed frame used to throw straight out of onmessage
                // (uncaught, and it aborted processing that message). Guard the
                // parse so a bad frame is logged and skipped; the socket lives on.
                // Kept as `any` to match the rest of this handler, which reads
                // many dynamically-shaped fields off the parsed message.
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                let msg: any;
                try {
                    msg = JSON.parse(event.data);
                    if (msg.type === "trading") window.dispatchEvent(new CustomEvent("freya-trading", {detail: msg.payload}));
                    if (msg.type === "authoritative") {
                        setMissions(Object.fromEntries((msg.payload.missions as MissionPayload[]).map(m => [m.id,m])));
                        setApprovals(msg.payload.approvals);
                        return;
                    }
                } catch {
                    console.warn("Freyja: dropped an unparseable WebSocket frame.");
                    return;
                }
                if (!msg || typeof msg !== "object") return;

                if (msg.type === "state") {
                    setState(msg.value as FreyaState);
                    // Turn complete or barge-in → flush Freya's buffered words
                    if (msg.value === "interrupted") {
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
                    if (typeof msg.text === "string" && /^\[(SESSION ERROR|Connection lost)/.test(msg.text)) {
                        pushLinkError("session", `Gemini Live: ${msg.text.replace(/^\[|\]$/g, "")}`,
                            msg.text.startsWith("[SESSION ERROR")
                                ? "The voice session gave up reconnecting. Check the API key, quota and network, then press Start again."
                                : "The Gemini Live connection dropped and is reconnecting. See the server.py log for the exception.");
                    }
                    if (msg.speaker === "User") {
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
                    else if (msg.speaker === "Freya") {
                        // The completed server transcript is authoritative. Playback
                        // state can change between chunks and must not split a reply.
                        freyaBuffer.current = msg.text;
                        flushFreyaBuffer();
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
                } else if (msg.type === "image") {
                    // A new image Freya received (e.g. a screen capture) → show on the canvas.
                    // `dashboard: false` means it was aimed at the desktop popup only;
                    // absent means "yes" so screen captures keep their old behaviour.
                    if (msg.dashboard !== false) {
                        setImages((prev) => [
                            ...prev,
                            {
                                id: counter.current++,
                                data: msg.data,
                                label: msg.label || "Image",
                                timestamp: new Date(),
                            },
                        ].slice(-6));
                    }
                } else if (msg.type === "card") {
                    // Text (± a photo) Freya retrieved and put on screen.
                    const c = msg as CardEventPayload;
                    if (c.dashboard !== false) {
                        setCards((prev) => [
                            ...prev,
                            {
                                id: counter.current++,
                                title: c.title || "",
                                body: c.body || "",
                                source: c.source || "",
                                image: c.image ?? null,
                                url: c.url ?? null,
                                timestamp: new Date(),
                            },
                        ].slice(-6));
                    }
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
                } else if (msg.type === "orb_gesture") {
                    // Telemetry echo of a webcam hand gesture the backend already
                    // routed to Gemini via runtime.inject — HUD callout only, this
                    // never touches avatarIntent (no GLB animation actually plays).
                    setOrbGestureEvent({ gesture: String(msg.gesture ?? ""), seq: ++orbGestureSeq.current });
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
                    } else if (p.event === "assessed") {
                        setApprovals((prev) =>
                            prev.map((a) => (a.id === p.id ? { ...a, risk: p.risk } : a))
                        );
                    } else {
                        setApprovals((prev) => prev.filter((a) => a.id !== p.id));
                    }
                } else if (msg.type === "session") {
                    setSession(msg.payload as SessionInfo);
                } else if (["agent", "browser", "schedule", "ambient", "mcp"].includes(msg.type)) {
                    const { type, ...rest } = msg;

                    // Sub-agents and the browser operator get real, structured
                    // tracking (id → task → current step → done) so the
                    // dashboard can show what's actually running, rather than
                    // only scrolling past as opaque feed lines.
                    if ((type === "agent" || type === "browser") && rest.id) {
                        setAgents((prev) => {
                            const idx = prev.findIndex((a) => a.id === rest.id);
                            const incoming: AgentJob = {
                                id: String(rest.id),
                                // `agent` (not `type`) — the event family owns
                                // `type` on the wire, so the sub-agent's kind
                                // travels under its own key.
                                kind: String(type === "browser" ? "browser" : rest.agent || "agent"),
                                task: String(rest.task ?? (idx >= 0 ? prev[idx].task : "")),
                                status: String(rest.status ?? "working"),
                                step: rest.step ?? (idx >= 0 ? prev[idx].step : null),
                                startedAt: idx >= 0 ? prev[idx].startedAt : Date.now() / 1000,
                                result: rest.result ?? (idx >= 0 ? prev[idx].result : null),
                            };
                            if (idx < 0) return [incoming, ...prev].slice(0, 12);
                            const next = [...prev];
                            next[idx] = incoming;
                            return next;
                        });
                    }

                    // Everything still shows in the tool feed for the scene log.
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
        return () => { disposed = true; clearTimeout(reconnectTimer); ws.current?.close(); };
        // Intentionally empty: the socket must be opened exactly once. Config
        // reloading goes through loadConfigRef so it never becomes a dependency.
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

    // null = follow the Windows default device; undefined = leave unchanged.
    const setAudioDevice = useCallback((inputDeviceIndex?: number | null, outputDeviceIndex?: number | null) => {
        send({
            type: "set_audio_device",
            ...(inputDeviceIndex !== undefined ? { input_device_index: inputDeviceIndex } : {}),
            ...(outputDeviceIndex !== undefined ? { output_device_index: outputDeviceIndex } : {}),
        });
        setConfig((prev) => prev ? {
            ...prev,
            ...(inputDeviceIndex !== undefined ? { input_device_index: inputDeviceIndex } : {}),
            ...(outputDeviceIndex !== undefined ? { output_device_index: outputDeviceIndex } : {}),
        } : prev);
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

    const sendGestureTouch = useCallback((gesture: string) => {
        send({ type: "gesture_touch", gesture });
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
        linkErrors,
        linkStats,
        pingMs,
        clearLinkErrors,
        transcript,
        liveText,
        toolLog,
        images,
        cards,
        newsItems,
        config,
        audioDevices,
        agents,
        session,
        activeMode,
        micPaused,
        memoryVersion,
        approvals,
        missions,
        activeMission,
        avatarIntent,
        orbGestureEvent,
        suggestions,
        contextInfo,
        persona,
        // Actions
        startFreya,
        stopFreya,
        setModel,
        setVoice,
        setAudioDevice,
        // Re-read /config after a change made outside this hook (the persona customizer).
        reloadConfig: loadBackendConfig,
        setMode,
        toggleListening,
        respondApproval,
        sendGestureTouch,
        cancelMission,
        respondSuggestion,
        clearTranscript,
        clearToolLog,
    };
}
