"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import Chart, {
  type ChartTool,
  type Drawing,
  type ChartOptions,
} from "./Chart";
import type { Session, Report, Candle } from "./types";
import {
  TOOL_GROUPS,
  MAX_DRAWINGS,
  drawingSummary,
  isDrawing,
  toolIcon,
  toolLabel,
} from "./drawingTools";
import { useSharedFreyaSocket } from "../components/FreyaSocketProvider";
import "./workspace.css";
const API = "http://localhost:8000/trading";
async function api(path: string, body?: unknown, signal?: AbortSignal) {
  const r = await fetch(API + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request rejected. Check inputs and refresh the workspace.",
    );
  return data;
}
const money = (n: string | number) =>
  Number(n).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
const num = (n: string | number) =>
  Number(n).toLocaleString(undefined, { maximumFractionDigits: 6 });
type Journal = {
  id: number;
  session: string;
  action: string;
  as_of: number;
  note?: string;
  thesis?: { text: string; invalidation: string };
};
type Learning = {
  review_count: number;
  followed_plan_count: number;
  analysis_count: number;
  known_ai_tokens: number;
  ai_cost_usd: string | null;
};
type Panel =
  "orders" | "positions" | "fills" | "journal" | "progress" | "analysis";
type LivePrice = { price: string; change_24h: string; fetched_at: number };
const MARKETS: [string, string, string][] = [
  ["BTC-USD", "Bitcoin", "B"],
  ["ETH-USD", "Ethereum", "Ξ"],
  ["SOL-USD", "Solana", "S"],
  ["XRP-USD", "XRP", "X"],
  ["DOGE-USD", "Dogecoin", "Ð"],
  ["ADA-USD", "Cardano", "A"],
  ["AVAX-USD", "Avalanche", "V"],
  ["LINK-USD", "Chainlink", "L"],
  ["LTC-USD", "Litecoin", "Ł"],
];
const coinIcon = (symbol: string) =>
  MARKETS.find(([m]) => m === symbol)?.[2] ?? "¤";
const TRADING_TOOL_LABELS: Record<string, string> = {
  get_trading_lab_context: "👀 Read your chart",
  get_trading_learner_profile: "📘 Checked what you know",
  update_trading_learner_profile: "📝 Updated your learning progress",
  draw_on_chart: "✎ Drew",
  clear_my_drawings: "🧽 Cleared her drawings",
  paper_order: "🧾 Placed a paper order",
  record_trading_thesis: "💡 Saved your thesis",
};
const LIVE_MS = 5000;
const CANDLE_POLL_MS = 15000;
export default function TradingPage() {
  const {
    connected,
    state: voiceState,
    session: voiceSession,
    transcript,
    toolLog,
    liveText,
    micPaused,
    startFreya,
    stopFreya,
    toggleListening,
  } = useSharedFreyaSocket();
  const voiceOn = voiceSession?.running ?? voiceState !== "idle";
  const [s, setS] = useState<Session | null>(null);
  const current = useRef<Session | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [feedError, setFeedError] = useState("");
  const [busy, setBusy] = useState(false);
  const mutationLock = useRef(false);
  const [symbol, setSymbol] = useState("BTC-USD");
  const [interval, setIntervalValue] = useState(900);
  const [mode, setMode] = useState("independent");
  const [source, setSource] = useState("observation");
  const [date, setDate] = useState("2025-01-01");
  const [panel, setPanel] = useState<Panel>("orders");
  const [sideTab, setSideTab] = useState("ticket");
  const [options, setOptions] = useState<ChartOptions>({
    ema: true,
    volume: true,
    rsi: true,
    line: false,
  });
  const [tool, setTool] = useState<ChartTool>("cursor");
  const [fit, setFit] = useState(0);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [groupPick, setGroupPick] = useState<Record<string, ChartTool>>({});
  const [drawingsHidden, setDrawingsHidden] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1500);
  const [thesis, setThesis] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [side, setSide] = useState("buy");
  const [kind, setKind] = useState("market");
  const [quantity, setQuantity] = useState("0.01");
  const [price, setPrice] = useState("");
  const [target, setTarget] = useState("");
  const [journal, setJournal] = useState<Journal[]>([]);
  const [learning, setLearning] = useState<Learning | null>(null);
  const [review, setReview] = useState("");
  const [followed, setFollowed] = useState(true);
  const [provider, setProvider] = useState("gemini");
  const [openai, setOpenai] = useState(false);
  const [image, setImage] = useState<string | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const analysisAbort = useRef<AbortController | null>(null);
  const [live, setLive] = useState<Record<string, LivePrice>>({});
  const [forming, setForming] = useState<Candle | null>(null);
  const [liveOk, setLiveOk] = useState(true);
  const accept = useCallback((state: Session, replace = false) => {
    if (
      !replace &&
      current.current &&
      (current.current.id !== state.id ||
        current.current.revision > state.revision)
    )
      return;
    current.current = state;
    setS(state);
    if (replace) {
      setSelected(null);
      setThesis(state.thesis?.text ?? "");
      setInvalidation(state.thesis?.invalidation ?? "");
      setSymbol(state.symbol);
      setIntervalValue(state.interval);
      setMode(state.mode);
      setSource(state.environment === "observation" ? "observation" : "historical");
      setPlaying(false);
      setForming(null);
      setLearning(null);
      setReview("");
      setReport(null);
      setError("");
      setFeedError("");
      try {
        const saved = JSON.parse(
          localStorage.getItem(`freya-drawings-${state.id}`) ?? "[]",
        );
        setDrawings(
          Array.isArray(saved)
            ? saved
                // Older saves used "level" for what is now a horizontal line.
                .map((d) => (d && d.kind === "level" ? { ...d, kind: "hline" } : d))
                .filter(isDrawing)
                .slice(0, MAX_DRAWINGS)
            : [],
        );
        localStorage.setItem("freya-trading-session", state.id);
      } catch {
        setDrawings([]);
      }
      window.history.replaceState(null, "", `/trading?session=${state.id}${state.environment === "observation" ? "" : "&replay=1"}`);
    }
  }, []);
  const refresh = useCallback(
    async (id: string) => {
      accept(await api(`/sessions/${id}`));
    },
    [accept],
  );
  useEffect(() => {
    const controller = new AbortController();
    const explicitId = new URLSearchParams(window.location.search).get("session");
    const replayRequested = new URLSearchParams(window.location.search).get("replay") === "1";
    const id = explicitId ||
      localStorage.getItem("freya-trading-session");
    const initialize = async () => {
      setBusy(true);
      mutationLock.current = true;
      try {
        let state: Session | null = null;
        if (id) {
          try { state = await api(`/sessions/${id}`, undefined, controller.signal); }
          catch (e) { if (explicitId || controller.signal.aborted) throw e; }
        }
        // A session URL is also written automatically by the workspace. Only
        // explicitly marked replay links may restore non-live market data.
        if (!state || (!replayRequested && state.environment !== "observation")) {
          state = await api("/observation", {
            key: crypto.randomUUID(), symbol: state?.symbol ?? "BTC-USD",
            interval: state?.interval ?? 900, mode: state?.mode ?? "independent",
          }, controller.signal);
        }
        if (!controller.signal.aborted && state) {
          accept(state, true);
          const restoredId = state.id;
          void api(`/analysis/${restoredId}`, undefined, controller.signal)
            .then((r) => {
              if (!controller.signal.aborted && current.current?.id === restoredId) setReport(r);
            }).catch(() => {});
        }
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Live market data unavailable. Retry with New session.");
      } finally {
        if (!controller.signal.aborted) {
          mutationLock.current = false;
          setBusy(false);
        }
      }
    };
    void initialize();
    void api("/providers", undefined, controller.signal)
      .then((r) => setOpenai(r.openai === true))
      .catch(() => {});
    return () => controller.abort();
  }, [accept]);
  useEffect(() => {
    if (connected && current.current)
      void refresh(current.current.id).catch((e) => setError(e.message));
  }, [connected, refresh]);
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      const id = detail.session_id;
      if (id !== current.current?.id) return;
      // Freya drawing (or clearing her drawings) on the chart by voice.
      if (detail.event === "draw" || detail.event === "clear_freya") {
        setDrawings((prev) => {
          const next =
            detail.event === "draw"
              ? [
                  ...prev,
                  { ...detail.drawing, id: crypto.randomUUID(), author: "freya" },
                ]
                  .filter(isDrawing)
                  .slice(-MAX_DRAWINGS)
              : prev.filter((d) => d.author !== "freya");
          try {
            localStorage.setItem(`freya-drawings-${id}`, JSON.stringify(next));
          } catch {}
          return next;
        });
        setDrawingsHidden(false);
        if (detail.event === "draw" && typeof detail.draw_id === "string")
          void api(`/drawings/ack/${detail.draw_id}`, {}).catch(() => {});
        return;
      }
      void refresh(id).catch((e) => setError(e.message));
    };
    window.addEventListener("freya-trading", handler);
    return () => window.removeEventListener("freya-trading", handler);
  }, [refresh]);
  useEffect(
    () => () => {
      analysisAbort.current?.abort();
    },
    [],
  );
  useEffect(() => {
    if (!s) return;
    const id = s.id;
    let client = sessionStorage.getItem("freya-workspace-client");
    if (!client) {
      client = crypto.randomUUID();
      sessionStorage.setItem("freya-workspace-client", client);
    }
    const sync = () => {
      void api("/workspace", {
        client_id: client,
        session_id: id,
        panel,
        candle_id: selected,
        active: document.visibilityState === "visible",
        focused: document.hasFocus(),
        ...options,
        drawings: drawingSummary(drawings),
      }).catch(() => {});
    };
    sync();
    const timer = setInterval(sync, 20000);
    window.addEventListener("focus", sync);
    window.addEventListener("blur", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", sync);
      window.removeEventListener("blur", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [s?.id, panel, selected, options, drawings, voiceOn, voiceState === "idle"]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const release = () => {
      const client = sessionStorage.getItem("freya-workspace-client");
      if (client && current.current)
        void fetch(API + "/workspace", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          keepalive: true,
          body: JSON.stringify({
            client_id: client,
            session_id: current.current.id,
            active: false,
          }),
        }).catch(() => {});
    };
    window.addEventListener("pagehide", release);
    return () => {
      window.removeEventListener("pagehide", release);
      release();
    };
  }, []);
  const run = useCallback(async (fn: () => Promise<void>) => {
    if (mutationLock.current) return;
    mutationLock.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setPlaying(false);
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      mutationLock.current = false;
      setBusy(false);
    }
  }, []);
  const mutate = useCallback(
    async (action: string, body: object) => {
      const state = current.current;
      if (!state) return;
      await run(async () => {
        try {
          accept(
            await api(`/sessions/${state.id}/${action}`, {
              key: crypto.randomUUID(),
              revision: state.revision,
              ...body,
            }),
          );
        } catch (e) {
          await refresh(state.id).catch(() => {});
          throw e;
        }
      });
    },
    [accept, refresh, run],
  );
  useEffect(() => {
    if (!playing || busy || !s || s.finished || s.environment === "observation")
      return;
    const timer = setTimeout(() => void mutate("advance", { bars: 1 }), speed);
    return () => clearTimeout(timer);
  }, [playing, busy, s, mutate, speed]);
  useEffect(() => {
    let stopped = false;
    const tick = () => {
      if (document.visibilityState !== "visible") return;
      void api("/live")
        .then((r: { prices: (LivePrice & { symbol: string })[] }) => {
          if (stopped) return;
          setLive((prev) => {
            const next = { ...prev };
            for (const p of r.prices) {
              if (!next[p.symbol] || p.fetched_at > next[p.symbol].fetched_at) next[p.symbol] = p;
            }
            return next;
          });
          setLiveOk(r.prices.some((p) => Date.now() / 1000 - p.fetched_at < 15));
        })
        .catch(() => {
          if (!stopped) setLiveOk(false);
        });
    };
    tick();
    const timer = setInterval(tick, LIVE_MS);
    document.addEventListener("visibilitychange", tick);
    // Tick-by-tick prices straight from Coinbase's public feed (no key). The
    // REST poll above keeps running so the backend (and Freya) see prices too.
    let feed: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout>;
    const ticks: Record<string, LivePrice> = {};
    const flush = setInterval(() => {
      const batch = Object.entries(ticks);
      if (!batch.length) return;
      for (const [k] of batch) delete ticks[k];
      setLive((prev) => ({ ...prev, ...Object.fromEntries(batch) }));
      setLiveOk(true);
    }, 400);
    const open = () => {
      if (stopped) return;
      feed = new WebSocket("wss://ws-feed.exchange.coinbase.com");
      feed.onopen = () =>
        feed?.send(
          JSON.stringify({
            type: "subscribe",
            product_ids: MARKETS.map(([m]) => m),
            channels: ["ticker"],
          }),
        );
      feed.onmessage = (event) => {
        try {
          const m = JSON.parse(event.data);
          if (m.type !== "ticker" || !m.price || !m.open_24h) return;
          ticks[m.product_id] = {
            price: m.price,
            change_24h: ((+m.price / +m.open_24h - 1) * 100).toFixed(2),
            fetched_at: Date.now() / 1000,
          };
        } catch {}
      };
      feed.onclose = () => {
        if (!stopped) retry = setTimeout(open, 3000);
      };
    };
    open();
    return () => {
      stopped = true;
      clearInterval(timer);
      clearInterval(flush);
      clearTimeout(retry);
      feed?.close();
      document.removeEventListener("visibilitychange", tick);
    };
  }, []);
  const liveSymbol = s?.environment === "observation" ? s.symbol : null;
  const liveInterval = s?.interval ?? 0;
  useEffect(() => {
    if (!liveSymbol) return;
    let stopped = false;
    const load = () => {
      if (document.visibilityState !== "visible") return;
      void api(`/live/candle?symbol=${liveSymbol}&interval=${liveInterval}`)
        .then((r: { candle: Candle | null }) => {
          if (!stopped) setForming(r.candle);
        })
        .catch(() => {});
    };
    load();
    const timer = setInterval(load, 5000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [liveSymbol, liveInterval]);
  const tick = liveSymbol ? live[liveSymbol] : undefined;
  const tickPrice = tick?.price;
  const lastClosedTime = s?.candles.at(-1)?.time ?? 0;
  const liveCandle =
    forming && forming.time > lastClosedTime
      ? tickPrice &&
        Math.floor(tick.fetched_at / liveInterval) * liveInterval ===
          forming.time
        ? {
            ...forming,
            close: tickPrice,
            high: String(Math.max(+forming.high, +tickPrice)),
            low: String(Math.min(+forming.low, +tickPrice)),
          }
        : forming
      : null;
  const observationId = s?.environment === "observation" ? s.id : null;
  useEffect(() => {
    if (!observationId) return;
    let stopped = false;
    const poll = () => {
      if (mutationLock.current || document.visibilityState !== "visible")
        return;
      void api(`/observation/${observationId}/poll`, {})
        .then((state) => {
          if (!stopped) {
            accept(state);
            setFeedError("");
          }
        })
        .catch((e) => {
          if (!stopped) setFeedError(e.message);
        });
    };
    poll();
    const timer = setInterval(poll, CANDLE_POLL_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [observationId, accept]);
  useEffect(() => {
    if (!s) return;
    const controller = new AbortController();
    if (panel === "journal")
      void api("/journal", undefined, controller.signal)
        .then(setJournal)
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    if (panel === "progress")
      void api(`/progress/${s.id}`, undefined, controller.signal)
        .then(setLearning)
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    return () => controller.abort();
  }, [panel, s?.id, s?.revision]); // eslint-disable-line react-hooks/exhaustive-deps
  async function create() {
    setPlaying(false);
    analysisAbort.current?.abort();
    await run(async () => {
      const body = { key: crypto.randomUUID(), symbol, interval, mode };
      const state = await api(
        source === "observation"
            ? "/observation"
            : "/historical",
        source === "historical"
          ? {
              ...body,
              start: Date.parse(date) / 1000,
              end: Date.parse(date) / 1000 + interval * 500,
            }
          : body,
      );
      accept(state, true);
    });
  }
  function saveDrawings(next: Drawing[]) {
    if (!s) return;
    setDrawings(next);
    try {
      localStorage.setItem(`freya-drawings-${s.id}`, JSON.stringify(next));
    } catch {
      setError(
        "Drawing storage is full. This change is kept only until reload.",
      );
    }
  }
  async function analyze() {
    if (!s || analysisBusy) return;
    setPlaying(false);
    setAnalysisBusy(true);
    setError("");
    const id = s.id;
    const controller = new AbortController();
    analysisAbort.current = controller;
    try {
      const r = await api(
        `/analysis/${id}`,
        { provider, image_base64: image },
        controller.signal,
      );
      if (current.current?.id === id) {
        setReport(r);
        setPanel("analysis");
      }
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalysisBusy(false);
    }
  }
  async function talk() {
    setSideTab("guide");
    if (!connected) {
      setError("Freya's backend is offline. Start server.py to talk with her.");
      return;
    }
    if (!s) {
      setError("Wait for the chart to load before starting chart voice help.");
      return;
    }
    try {
      let client = sessionStorage.getItem("freya-workspace-client");
      if (!client) {
        client = crypto.randomUUID();
        sessionStorage.setItem("freya-workspace-client", client);
      }
      await api("/workspace", { client_id: client, session_id: s.id, panel,
        candle_id: selected, active: true, focused: true, ...options,
        drawings: drawingSummary(drawings) });
      if (!voiceOn) startFreya();
    } catch {
      setError("Could not share the active chart with Freya. Try again.");
    }
  }
  function evidence(id: string) {
    if (!s?.candles.some((c) => c.id === id)) {
      setError("This evidence is not in the current visible session.");
      return;
    }
    setSelected(id);
    setSideTab("guide");
  }
  const last = s?.candles.at(-1);
  const previous = s?.candles.at(-2);
  const shown = s?.symbol ?? symbol;
  const tickerLive =
    !s || s.environment === "observation" ? live[shown] : undefined;
  const change = tickerLive
    ? +tickerLive.change_24h
    : last && previous
      ? (+last.close / +previous.close - 1) * 100
      : 0;
  const pending = s?.orders.filter((o) => o.status === "pending") ?? [];
  const currentReport = report && report.snapshot?.id === s?.id;
  const refPrice = kind === "limit" ? +price : +(last?.close ?? 0);
  const notional = +quantity * refPrice;
  const estimatedFee = notional * +(s?.fee ?? 0);
  // Live profit/loss. Fills give the average cost (buy fees included) and realized
  // P&L; the position is marked at the real-time tick in live sessions, otherwise at
  // the latest visible close. Display only; the ledger stays on closed candles.
  const STARTING_CASH = 10000;
  const markPrice = s
    ? s.environment === "observation" && live[s.symbol]
      ? +live[s.symbol].price
      : +(last?.close ?? 0)
    : 0;
  const pnl = (() => {
    let qty = 0,
      cost = 0,
      realized = 0;
    for (const f of s?.fills ?? []) {
      const q = +f.quantity,
        p = +f.price,
        fee = +f.fee;
      if (f.side === "buy") {
        qty += q;
        cost += q * p + fee;
      } else if (qty > 0) {
        const avg = cost / qty;
        realized += q * p - fee - avg * q;
        cost -= avg * q;
        qty -= q;
      }
    }
    const held = +(s?.quantity ?? 0);
    const avgCost = held > 0 && qty > 0 ? cost / qty : 0;
    const unrealized = held > 0 ? held * markPrice - avgCost * held : 0;
    const equity = s ? +s.cash + held * markPrice : STARTING_CASH;
    return {
      avgCost,
      unrealized,
      unrealizedPct: avgCost > 0 ? (markPrice / avgCost - 1) * 100 : 0,
      realized,
      equity,
      total: equity - STARTING_CASH,
      totalPct: ((equity - STARTING_CASH) / STARTING_CASH) * 100,
    };
  })();
  const signed = (n: number) => `${n >= 0 ? "+" : "−"}${money(Math.abs(n))}`;
  const tone = (n: number) =>
    Math.abs(n) < 0.005 ? undefined : n > 0 ? "positive" : "negative";
  const liveMark = s?.environment === "observation" && !!live[s.symbol];
  return (
    <main className="trading-workspace">
      <header className="workspace-top">
        <Link href="/" className="brand-mark">
          F<span>REYA</span>
          <small>TRADING LAB</small>
        </Link>
        <span className="workspace-path">
          Workspace <span>/</span> Market practice
        </span>
        <div className="top-right">
          <span className="simulation-badge">PAPER ACCOUNT</span>
          <span className="connection">
            <i className={connected ? "online" : ""} />
            {connected ? "Freya connected" : "Standalone mode"}
          </span>
          <button
            className={`subtle voice-toggle ${voiceOn ? "on" : ""}`}
            onClick={() => (voiceOn ? stopFreya() : talk())}
            disabled={!connected}
          >
            {voiceOn ? "■ End conversation" : "🎙 Talk to Freya"}
          </button>
        </div>
      </header>
      <section className="market-bar">
        <div className="market-title">
          <span className="coin-icon">
            {coinIcon(shown)}
          </span>
          <div>
            <h1>
              {s?.symbol ?? symbol}
              <span>
                {s?.interval ? s.interval / 60 : interval / 60}m · SPOT
              </span>
            </h1>
            <small>{s?.environment === "observation" ? "Coinbase Exchange · live market" : s?.source ?? "Loading live market data…"}</small>
          </div>
        </div>
        <div className="market-price">
          <strong>
            {tickerLive
              ? money(tickerLive.price)
              : last
                ? money(last.close)
                : "—"}
          </strong>
          <span className={change >= 0 ? "positive" : "negative"}>
            {change >= 0 ? "+" : ""}
            {change.toFixed(2)}%{" "}
            <small>
              {tickerLive
                ? liveOk
                  ? "24h · live"
                  : "24h · delayed"
                : "last bar"}
            </small>
          </span>
        </div>
        <div className="market-stat">
          <small>VISIBLE BARS</small>
          <b>{s?.candles.length ?? "—"}</b>
        </div>
        <div className="market-stat">
          <small>AS OF · UTC</small>
          <b>
            {last
              ? new Date((last.time + (s?.interval ?? 0)) * 1000)
                  .toISOString()
                  .slice(0, 16)
                  .replace("T", " ")
              : "—"}
          </b>
        </div>
      </section>
      {(error || feedError) && (
        <div role="alert" className="workspace-error">
          {error || feedError}
          <button aria-label="Dismiss error" onClick={() => { setError(""); setFeedError(""); }}>
            ×
          </button>
        </div>
      )}
      <div className="workspace-grid">
        <aside className="market-sidebar">
          <div className="section-heading">
            MARKETS{" "}
            <span>
              {MARKETS.length} instruments · {liveOk ? "live" : "offline"}
            </span>
          </div>
          {MARKETS.map(([ticker, name, icon]) => (
            <button
              key={ticker}
              className={`market-row ${symbol === ticker ? "active" : ""}`}
              onClick={() => setSymbol(ticker)}
            >
              <span className="small-coin">{icon}</span>
              <span>
                <b>{ticker}</b>
                <small>{name}</small>
              </span>
              <span className="market-row-price">
                {live[ticker] ? num(live[ticker].price) : "—"}
                {live[ticker] && (
                  <small
                    className={
                      +live[ticker].change_24h >= 0 ? "positive" : "negative"
                    }
                  >
                    {" "}
                    {+live[ticker].change_24h >= 0 ? "+" : ""}
                    {live[ticker].change_24h}%
                  </small>
                )}
              </span>
            </button>
          ))}
          <div className="session-setup">
            <h2>Practice session</h2>
            <label>
              Timeframe
              <select
                aria-label="Session timeframe"
                value={interval}
                onChange={(e) => setIntervalValue(+e.target.value)}
              >
                <option value={60}>1 minute</option>
                <option value={300}>5 minutes</option>
                <option value={900}>15 minutes</option>
                <option value={3600}>1 hour</option>
              </select>
            </label>
            <label>
              Data source
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="observation">Live market · paper money</option>
                <option value="historical">Coinbase historical replay</option>
              </select>
            </label>
            {source === "historical" && (
              <label>
                Start date
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </label>
            )}
            <label>
              Learning mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="independent">Independent · thesis first</option>
                <option value="coached">Coached practice</option>
              </select>
            </label>
            <button className="primary" disabled={busy} onClick={create}>
              {busy ? "Loading…" : s ? "New session" : "Start practice"}{" "}
              <span>↗</span>
            </button>
            <p className="muted">
              A new session starts with $10,000 virtual cash. Existing sessions
              stay in your journal.
            </p>
          </div>
          <div className="sidebar-lesson">
            <span>LEARN WITH INTENTION</span>
            <h3>
              Good decisions.
              <br />
              Then good habits.
            </h3>
            <p>Write your thesis before you see the next candle.</p>
            <button
              className="text-button"
              onClick={talk}
              disabled={!connected}
            >
              Show me how →
            </button>
          </div>
        </aside>
        <section className="workspace-center">
          <div className="chart-toolbar">
            <div className="toolbar-group">
              <button
                aria-pressed={!options.line}
                onClick={() => setOptions((o) => ({ ...o, line: false }))}
              >
                Candles
              </button>
              <button
                aria-pressed={options.line}
                onClick={() => setOptions((o) => ({ ...o, line: true }))}
              >
                Line
              </button>
            </div>
            <div className="toolbar-group">
              {(["ema", "volume", "rsi"] as const).map((key) => (
                <button
                  key={key}
                  aria-pressed={options[key]}
                  onClick={() => setOptions((o) => ({ ...o, [key]: !o[key] }))}
                >
                  {key === "ema"
                    ? "EMA 20"
                    : key === "rsi"
                      ? "RSI 14"
                      : "Volume"}
                </button>
              ))}
            </div>
            <button onClick={() => setFit((n) => n + 1)}>Fit chart</button>
            <button
              className="analysis-button"
              disabled={
                !s || analysisBusy || (!s.thesis && s.mode === "independent")
              }
              onClick={analyze}
            >
              ✧ {analysisBusy ? "Analyzing…" : "Chart analysis"}
            </button>
          </div>
          <div
            className="chart-stage"
            onPointerDown={(e) => {
              if (!(e.target as Element).closest(".drawing-toolbar"))
                setOpenGroup(null);
            }}
          >
            <nav className="drawing-toolbar" aria-label="Drawing tools">
              {TOOL_GROUPS.map((group) => {
                const current = group.tools.includes(tool)
                  ? tool
                  : (groupPick[group.id] ?? group.tools[0]);
                const multi = group.tools.length > 1;
                return (
                  <div key={group.id} className="tool-group">
                    <button
                      title={`${toolLabel(current)}${multi ? ` · ${group.label}` : ""}`}
                      aria-label={toolLabel(current)}
                      aria-pressed={tool === current}
                      aria-expanded={multi ? openGroup === group.id : undefined}
                      onClick={() => {
                        setTool(current);
                        setOpenGroup(
                          multi && openGroup !== group.id ? group.id : null,
                        );
                      }}
                    >
                      {toolIcon(current)}
                      {multi && <i className="tool-caret" />}
                    </button>
                    {openGroup === group.id && (
                      <div className="tool-flyout" role="menu">
                        <small>{group.label}</small>
                        {group.tools.map((t) => (
                          <button
                            key={t}
                            role="menuitemradio"
                            aria-checked={tool === t}
                            onClick={() => {
                              setTool(t);
                              setGroupPick((g) => ({ ...g, [group.id]: t }));
                              setOpenGroup(null);
                            }}
                          >
                            <span>{toolIcon(t)}</span>
                            {toolLabel(t)}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
              <span />
              <button
                title={drawingsHidden ? "Show drawings" : "Hide drawings"}
                aria-label={drawingsHidden ? "Show drawings" : "Hide drawings"}
                aria-pressed={drawingsHidden}
                onClick={() => setDrawingsHidden((h) => !h)}
              >
                {drawingsHidden ? "◌" : "◉"}
              </button>
              <button
                title="Undo drawing"
                aria-label="Undo drawing"
                disabled={!drawings.length}
                onClick={() => saveDrawings(drawings.slice(0, -1))}
              >
                ↶
              </button>
              <button
                title="Clear drawings"
                aria-label="Clear drawings"
                disabled={!drawings.length}
                onClick={() => saveDrawings([])}
              >
                ×
              </button>
              <small>
                {drawings.length}/{MAX_DRAWINGS}
              </small>
            </nav>
            {s ? (
              <Chart
                key={s.id}
                session={s}
                report={report}
                options={options}
                tool={tool}
                drawings={drawingsHidden ? [] : drawings}
                selected={selected}
                onSelect={setSelected}
                liveCandle={liveCandle}
                onErase={(id) =>
                  saveDrawings(drawings.filter((d) => d.id !== id))
                }
                onDraw={(d) => {
                  setDrawingsHidden(false);
                  if (drawings.length < MAX_DRAWINGS)
                    saveDrawings([...drawings, d]);
                  else
                    setError(
                      "Drawing limit reached. Remove an annotation to add another.",
                    );
                }}
                fit={fit}
              />
            ) : (
              <div className="workspace-empty">
                <span className="empty-chart-icon">⌁</span>
                <small>YOUR TRADING WORKSPACE</small>
                <h2>
                  Your next decision
                  <br />
                  starts here.
                </h2>
                <p>
                  Explore a chart. Form a thesis. Practice with virtual capital
                  and a guide by your side.
                </p>
                <button className="primary" onClick={create} disabled={busy}>
                  {busy ? "Loading…" : "Start practice replay →"}
                </button>
              </div>
            )}
          </div>
          <div className="replay-bar">
            <span className="replay-label">
              ◷{" "}
              {s?.environment === "observation" ? "LIVE MARKET" : "BAR REPLAY"}
            </span>
            {s?.environment === "observation" ? (
              <>
                <button
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      if (s) accept(await api(`/observation/${s.id}/poll`, {}));
                    })
                  }
                >
                  Refresh now ↻
                </button>
                <span className={s.feed_stale ? "negative" : "positive"}>
                  {s.feed_stale ? "Stale feed" : "Live"} · candles update
                  every {CANDLE_POLL_MS / 1000}s · orders fill on the next
                  closed candle
                </span>
              </>
            ) : (
              <>
                <button
                  aria-label={playing ? "Pause replay" : "Play replay"}
                  className="play-button"
                  disabled={!s || s.finished || (busy && !playing)}
                  onClick={() => setPlaying((p) => !p)}
                >
                  {playing ? "Ⅱ" : "▶"}
                </button>
                <button
                  disabled={!s || s.finished || busy}
                  onClick={() => {
                    setPlaying(false);
                    void mutate("advance", { bars: 1 });
                  }}
                >
                  Step →
                </button>
                <button
                  disabled={!s || s.finished || busy}
                  onClick={() => {
                    setPlaying(false);
                    void mutate("advance", { bars: 10 });
                  }}
                >
                  +10 bars
                </button>
                <select
                  aria-label="Replay speed"
                  value={speed}
                  onChange={(e) => setSpeed(+e.target.value)}
                >
                  <option value={3000}>Slow</option>
                  <option value={1500}>Normal</option>
                  <option value={600}>Fast</option>
                </select>
                <span className="muted">
                  {s?.finished
                    ? "Replay complete"
                    : playing
                      ? "Revealing one candle at a time"
                      : "Paused · no future candles revealed"}
                </span>
              </>
            )}
          </div>
          <div className="account-strip">
            {(
              [
                [
                  liveMark ? "Virtual equity · live" : "Virtual equity",
                  money(pnl.equity),
                ],
                [
                  "Unrealized P&L",
                  s && +s.quantity > 0
                    ? `${signed(pnl.unrealized)} (${pnl.unrealizedPct >= 0 ? "+" : ""}${pnl.unrealizedPct.toFixed(2)}%)`
                    : "No open position",
                  +(s?.quantity ?? 0) > 0 ? tone(pnl.unrealized) : undefined,
                ],
                [
                  "Total P&L",
                  s
                    ? `${signed(pnl.total)} (${pnl.totalPct >= 0 ? "+" : ""}${pnl.totalPct.toFixed(2)}%)`
                    : "—",
                  s ? tone(pnl.total) : undefined,
                ],
                ["Available cash", s ? money(+s.cash - +s.reserved_cash) : "—"],
                [
                  "Position",
                  s ? `${num(s.quantity)} ${s.symbol.split("-")[0]}` : "—",
                ],
                ["Fees paid", s ? money(s.fees) : "—"],
                ["Max drawdown", s ? `${(+s.drawdown * 100).toFixed(2)}%` : "—"],
              ] as [string, string, string?][]
            ).map(([label, value, className]) => (
              <div key={label}>
                <small>{label}</small>
                <strong className={className}>{value}</strong>
              </div>
            ))}
          </div>
          <section className="bottom-panel">
            <div className="panel-tabs">
              {(
                [
                  "orders",
                  "positions",
                  "fills",
                  "journal",
                  "progress",
                  "analysis",
                ] as Panel[]
              ).map((p) => (
                <button
                  key={p}
                  aria-pressed={panel === p}
                  onClick={() => setPanel(p)}
                >
                  {p}
                  {p === "orders" && <span>{pending.length}</span>}
                </button>
              ))}
            </div>
            <div className="panel-body">
              {panel === "orders" && (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Side / type</th>
                        <th>Quantity</th>
                        <th>Price / trigger</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s?.orders
                        .slice()
                        .reverse()
                        .map((o) => (
                          <tr key={o.id}>
                            <td>
                              <span
                                className={
                                  o.side === "buy" ? "positive" : "negative"
                                }
                              >
                                {o.side.toUpperCase()}
                              </span>{" "}
                              · {o.kind}
                            </td>
                            <td>{num(o.quantity)}</td>
                            <td>
                              {o.price ? money(o.price) : "Next eligible open"}
                            </td>
                            <td title={o.reason}>
                              {o.status}
                              {o.reason && (
                                <small className="negative">{o.reason}</small>
                              )}
                            </td>
                            <td>
                              {o.status === "pending" ? (
                                <button
                                  className="text-button"
                                  disabled={busy}
                                  onClick={() =>
                                    mutate("cancel", { order_id: o.id })
                                  }
                                >
                                  Cancel
                                </button>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {!s?.orders.length && (
                    <p className="panel-empty">
                      No orders yet. Save a thesis in the ticket to place your
                      first virtual order.
                    </p>
                  )}
                </div>
              )}
              {panel === "positions" && (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Instrument</th>
                        <th>Held</th>
                        <th>Reserved</th>
                        <th>Avg cost</th>
                        <th>{liveMark ? "Mark price · live" : "Mark price"}</th>
                        <th>Market value</th>
                        <th>Unrealized P&amp;L</th>
                        <th>Realized P&amp;L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s && (
                        <tr>
                          <td>{s.symbol}</td>
                          <td>{num(s.quantity)}</td>
                          <td>{num(s.reserved_quantity)}</td>
                          <td>{pnl.avgCost ? money(pnl.avgCost) : "—"}</td>
                          <td>{money(markPrice)}</td>
                          <td>{money(+s.quantity * markPrice)}</td>
                          <td className={tone(pnl.unrealized)}>
                            {+s.quantity > 0
                              ? `${signed(pnl.unrealized)} (${pnl.unrealizedPct >= 0 ? "+" : ""}${pnl.unrealizedPct.toFixed(2)}%)`
                              : "—"}
                          </td>
                          <td className={tone(pnl.realized)}>
                            {signed(pnl.realized)}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  <p className="muted">
                    Long spot positions only. Market value uses the latest
                    visible close.
                  </p>
                </div>
              )}
              {panel === "fills" && (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Time · UTC</th>
                        <th>Side</th>
                        <th>Quantity</th>
                        <th>Fill price</th>
                        <th>Fee</th>
                        <th>Execution</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s?.fills
                        .slice()
                        .reverse()
                        .map((f) => (
                          <tr key={f.order_id}>
                            <td>
                              {new Date(f.time * 1000)
                                .toISOString()
                                .slice(5, 16)
                                .replace("T", " ")}
                            </td>
                            <td
                              className={
                                f.side === "buy" ? "positive" : "negative"
                              }
                            >
                              {f.side}
                            </td>
                            <td>{num(f.quantity)}</td>
                            <td>{money(f.price)}</td>
                            <td>{money(f.fee)}</td>
                            <td>
                              {f.ambiguous
                                ? "Ambiguous · stop first"
                                : "Simulated"}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                  {!s?.fills.length && (
                    <p className="panel-empty">
                      Fills appear after an eligible candle is revealed.
                    </p>
                  )}
                </div>
              )}
              {panel === "journal" && (
                <div className="journal-list">
                  {journal.map((j) => (
                    <div key={j.id}>
                      <span className="journal-dot" />
                      <div>
                        <b>{j.action.replaceAll("_", " ")}</b>
                        <p>
                          {j.note ??
                            j.thesis?.text ??
                            "Recorded in the session audit"}
                        </p>
                      </div>
                      <a href={`/trading?session=${j.session}&replay=1`}>
                        {j.session === s?.id ? "This session" : "Open session"}{" "}
                        ↗
                      </a>
                    </div>
                  ))}
                  {!journal.length && (
                    <p className="panel-empty">
                      Your decisions and session history will appear here.
                    </p>
                  )}
                </div>
              )}
              {panel === "progress" && (
                <div className="progress-grid">
                  <div>
                    <h3>Process before outcome</h3>
                    <p>
                      {learning
                        ? `${learning.review_count} reviews · ${learning.followed_plan_count} followed the plan · ${learning.known_ai_tokens} recorded analysis tokens`
                        : "No reviews yet"}
                    </p>
                    <p className="muted">
                      {s?.sample_size ?? 0} fills in this session. Analysis
                      cost:{" "}
                      {learning?.ai_cost_usd
                        ? money(learning.ai_cost_usd)
                        : "unavailable"}
                      . Guide usage is shown on each reply.
                    </p>
                  </div>
                  <div>
                    <textarea
                      aria-label="Session review"
                      value={review}
                      onChange={(e) => setReview(e.target.value)}
                      placeholder="What did you learn from this decision?"
                    />
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={followed}
                        onChange={(e) => setFollowed(e.target.checked)}
                      />{" "}
                      I followed my plan
                    </label>
                    <button
                      className="subtle"
                      disabled={!s || busy || review.trim().length < 5}
                      onClick={() =>
                        run(async () => {
                          if (!s) return;
                          await api(`/review/${s.id}`, {
                            key: crypto.randomUUID(),
                            note: review,
                            followed_plan: followed,
                          });
                          setLearning(await api(`/progress/${s.id}`));
                          setReview("");
                        })
                      }
                    >
                      Save reflection
                    </button>
                  </div>
                </div>
              )}
              {panel === "analysis" && (
                <div className="analysis-panel">
                  <div className="analysis-settings">
                    <select
                      aria-label="Analysis provider"
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                    >
                      <option value="gemini">Gemini</option>
                      <option value="offline">Offline lesson</option>
                      {openai && <option value="openai">OpenAI</option>}
                    </select>
                    <label className="upload-label">
                      {image ? "Image attached ✓" : "Attach chart image"}
                      <input
                        type="file"
                        accept="image/png,image/jpeg"
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          setImage(null);
                          if (!f) return;
                          if (f.size > 2000000) {
                            setError("Image must be under 2 MB");
                            return;
                          }
                          const reader = new FileReader();
                          reader.onload = () =>
                            setImage(String(reader.result).split(",")[1]);
                          reader.readAsDataURL(f);
                        }}
                      />
                    </label>
                    {image && (
                      <button onClick={() => setImage(null)}>Remove</button>
                    )}
                    <button
                      className="subtle"
                      disabled={
                        !s ||
                        analysisBusy ||
                        (!s.thesis && s.mode === "independent")
                      }
                      onClick={analyze}
                    >
                      Explain decision
                    </button>
                    {analysisBusy && (
                      <button onClick={() => analysisAbort.current?.abort()}>
                        Cancel
                      </button>
                    )}
                  </div>
                  {currentReport && report ? (
                    <>
                      <p
                        className={
                          report.revision !== s?.revision ? "negative" : "muted"
                        }
                      >
                        {report.revision !== s?.revision
                          ? "Historical analysis · session has advanced"
                          : "Current snapshot"}{" "}
                        · {report.provider} · {report.usage.tokens ?? "unknown"}{" "}
                        tokens ·{" "}
                        {report.veto ? "Veto retained" : "Explanation only"}
                      </p>
                      <div className="analysis-stages">
                        {report.stages.map((stage) => (
                          <div key={stage.name}>
                            <small>{stage.status}</small>
                            <b>{stage.name}</b>
                            <p>{stage.finding}</p>
                          </div>
                        ))}
                      </div>
                      {report.error && (
                        <p className="negative">{report.error}</p>
                      )}
                      {report.analysis && (
                        <div className="analysis-copy">
                          <div>
                            {report.analysis.observations.map((o, i) => (
                              <p key={i}>
                                {o.text}
                                <span>
                                  {o.evidence.map((id) => (
                                    <button
                                      key={id}
                                      className="text-button"
                                      onClick={() => evidence(id)}
                                    >
                                      Inspect candle ↗
                                    </button>
                                  ))}
                                </span>
                              </p>
                            ))}
                          </div>
                          <div>
                            <p>
                              <b>Bullish scenario</b> {report.analysis.bullish}
                            </p>
                            <p>
                              <b>Bearish scenario</b> {report.analysis.bearish}
                            </p>
                            <p>
                              <b>Invalidation</b> {report.analysis.invalidation}
                            </p>
                            <p className="positive">{report.analysis.lesson}</p>
                          </div>
                        </div>
                      )}
                      <details>
                        <summary>Snapshot & audit</summary>
                        <pre>{JSON.stringify(report, null, 2)}</pre>
                      </details>
                    </>
                  ) : (
                    <p className="panel-empty">
                      Ask for a chart explanation when you are ready.
                      Independent practice requires your thesis first.
                    </p>
                  )}
                </div>
              )}
            </div>
          </section>
        </section>
        <aside className="workspace-right">
          <div className="right-tabs">
            <button
              aria-pressed={sideTab === "ticket"}
              onClick={() => setSideTab("ticket")}
            >
              Order ticket
            </button>
            <button
              aria-pressed={sideTab === "guide"}
              onClick={() => setSideTab("guide")}
            >
              🎙 Talk with Freya
            </button>
          </div>
          {sideTab === "ticket" ? (
            <div className="ticket">
              <div className="section-heading">
                YOUR DECISION <span>Simulation only</span>
              </div>
              <label>
                Thesis
                <textarea
                  value={thesis}
                  onChange={(e) => setThesis(e.target.value)}
                  placeholder="What do you see? What do you expect next?"
                />
              </label>
              <label>
                Invalidation
                <input
                  value={invalidation}
                  onChange={(e) => setInvalidation(e.target.value)}
                  placeholder="What would change your mind?"
                />
              </label>
              <button
                className="subtle full"
                disabled={
                  !s ||
                  busy ||
                  thesis.trim().length < 5 ||
                  invalidation.trim().length < 3
                }
                onClick={() => mutate("thesis", { thesis, invalidation })}
              >
                {s?.thesis ? "Update thesis" : "Save thesis"}
              </button>
              {s?.thesis && (
                <p className="saved-thesis">✓ Recorded: {s.thesis.text}</p>
              )}
              <hr />
              <div className="side-switch">
                <button
                  className={side === "buy" ? "buy-active" : ""}
                  onClick={() => setSide("buy")}
                >
                  Buy / Long
                </button>
                <button
                  className={side === "sell" ? "sell-active" : ""}
                  onClick={() => setSide("sell")}
                >
                  Sell / Close
                </button>
              </div>
              <label>
                Order type
                <select
                  value={kind}
                  onChange={(e) => {
                    setKind(e.target.value);
                    if (e.target.value === "bracket") setSide("sell");
                  }}
                >
                  {["market", "limit", "stop", "bracket"].map((k) => (
                    <option key={k}>{k}</option>
                  ))}
                </select>
              </label>
              <label>
                Quantity <span>{s?.symbol.split("-")[0] ?? "units"}</span>
                <input
                  inputMode="decimal"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                />
              </label>
              {kind !== "market" && (
                <label>
                  Limit / stop price
                  <input
                    inputMode="decimal"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                  />
                </label>
              )}
              {kind === "bracket" && (
                <label>
                  Take-profit target
                  <input
                    inputMode="decimal"
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                  />
                </label>
              )}
              <div className="ticket-preview">
                <div>
                  <span>Reference notional</span>
                  <b>{Number.isFinite(notional) ? money(notional) : "—"}</b>
                </div>
                <div>
                  <span>Estimated fee</span>
                  <b>
                    {Number.isFinite(estimatedFee) ? money(estimatedFee) : "—"}
                  </b>
                </div>
                <div>
                  <span>Slippage</span>
                  <b>{s ? `${(+s.slippage * 100).toFixed(2)}%` : "—"}</b>
                </div>
                <div>
                  <span>Available cash</span>
                  <b>{s ? money(+s.cash - +s.reserved_cash) : "—"}</b>
                </div>
              </div>
              <button
                className={`submit-order ${side}`}
                disabled={
                  !s ||
                  busy ||
                  !s.thesis ||
                  s.finished ||
                  !Number.isFinite(+quantity) ||
                  +quantity <= 0
                }
                onClick={() => {
                  setPlaying(false);
                  void mutate("order", {
                    side,
                    kind,
                    quantity,
                    ...(kind !== "market" ? { price } : {}),
                    ...(kind === "bracket" ? { target } : {}),
                  });
                }}
              >
                Place virtual {side} order
              </button>
              <p className="muted">
                Actual simulated fills depend on later eligible candles. Gap
                prices may differ. No broker or real money is connected.
              </p>
            </div>
          ) : (
            <div className="freya-guide">
              <div className="guide-intro">
                <div className="guide-orb">✧</div>
                <h2>
                  A little clarity.
                  <br />A better decision.
                </h2>
                <p>
                  Talk it through out loud. Freya reads this workspace directly
                  (chart, candles, indicators and your paper account), no
                  screenshots needed.
                </p>
              </div>
              <div className="guide-context">
                <i />{" "}
                {s
                  ? `${s.symbol} · ${s.interval / 60}m · ${selected ? "selected candle" : "latest candle"}`
                  : "Open a session so Freya has a chart to discuss"}
              </div>
              <div className="voice-controls">
                <span className={`voice-state ${voiceState}`}>
                  {!connected
                    ? "Backend offline"
                    : !voiceOn
                      ? "Not talking"
                      : micPaused
                        ? "Mic muted"
                        : voiceState === "speaking"
                          ? "Freya is speaking…"
                          : "Listening…"}
                </span>
                {voiceOn ? (
                  <>
                    <button onClick={toggleListening}>
                      {micPaused ? "Unmute mic" : "Mute mic"}
                    </button>
                    <button onClick={stopFreya}>End</button>
                  </>
                ) : (
                  <button
                    className="primary full"
                    disabled={!connected}
                    onClick={talk}
                  >
                    🎙 Start talking
                  </button>
                )}
              </div>
              {!voiceOn && (
                <div className="quick-questions">
                  <small className="muted">Try saying:</small>
                  {[
                    "What's happening on this chart?",
                    "Explain the candle I selected",
                    "What does RSI tell me here?",
                    "Help me write a thesis",
                  ].map((q) => (
                    <p key={q} className="user-question">
                      “{q}”
                    </p>
                  ))}
                </div>
              )}
              <div className="guide-messages" aria-live="polite">
                {transcript.slice(-16).map((t) => (
                  <p
                    key={t.id}
                    className={
                      t.speaker === "User" ? "user-question" : "guide-answer"
                    }
                  >
                    {t.text}
                  </p>
                ))}
                {liveText && <p className="guide-answer">{liveText}</p>}
              </div>
              {voiceOn && (
                <div className="freya-actions" aria-live="polite">
                  <small>Freya&apos;s actions</small>
                  {toolLog
                    .filter((t) => TRADING_TOOL_LABELS[t.name])
                    .slice(-5)
                    .map((t) => {
                      let visible: boolean | null = null;
                      try {
                        visible = JSON.parse(t.result).visible ?? null;
                      } catch {}
                      return (
                        <p
                          key={t.id}
                          className={visible === false ? "negative" : undefined}
                        >
                          {TRADING_TOOL_LABELS[t.name]}
                          {t.name === "draw_on_chart" &&
                            ` · ${String(t.args.kind ?? "")}${
                              visible === true
                                ? " · on your chart"
                                : visible === false
                                  ? " · did not appear"
                                  : ""
                            }`}
                        </p>
                      );
                    })}
                  {!toolLog.some((t) => TRADING_TOOL_LABELS[t.name]) && (
                    <p className="muted">None yet</p>
                  )}
                </div>
              )}
              <p className="muted">
                Voice uses the microphone and speakers on the computer running
                Freya. She can explain and coach, but she only places paper
                orders if you explicitly ask.
              </p>
            </div>
          )}
        </aside>
      </div>
      <footer className="workspace-footer">
        <span>
          <i />{" "}
          {s?.environment === "observation"
            ? "READ-ONLY MARKET DATA"
            : "HISTORICAL / SAMPLE REPLAY"}
        </span>
        <span>
          {s?.flags.length
            ? `${s.flags.length} data quality flags · new orders may be blocked`
            : "Virtual execution · long spot only · USD account"}
        </span>
        <span>Learn the process. Keep the evidence.</span>
      </footer>
    </main>
  );
}
