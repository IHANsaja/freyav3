"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import Chart, {
  type ChartTool,
  type Drawing,
  type ChartOptions,
} from "./Chart";
import type { Session, Report, GuideReply } from "./types";
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
export default function TradingPage() {
  const { connected } = useSharedFreyaSocket();
  const [s, setS] = useState<Session | null>(null);
  const current = useRef<Session | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mutationLock = useRef(false);
  const [symbol, setSymbol] = useState("BTC-USD");
  const [interval, setIntervalValue] = useState(900);
  const [mode, setMode] = useState("independent");
  const [source, setSource] = useState("sample");
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
  const [question, setQuestion] = useState("");
  const [guideProvider, setGuideProvider] = useState("local");
  const [messages, setMessages] = useState<
    { question: string; reply: GuideReply }[]
  >([]);
  const [guideBusy, setGuideBusy] = useState(false);
  const guideAbort = useRef<AbortController | null>(null);
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
      setPlaying(false);
      setMessages([]);
      setLearning(null);
      setReview("");
      setReport(null);
      setError("");
      try {
        const saved = JSON.parse(
          localStorage.getItem(`freya-drawings-${state.id}`) ?? "[]",
        );
        setDrawings(
          Array.isArray(saved)
            ? saved
                .filter(
                  (d) =>
                    d &&
                    typeof d.id === "string" &&
                    (d.kind === "level" || d.kind === "trend") &&
                    Array.isArray(d.points) &&
                    d.points.length === (d.kind === "level" ? 1 : 2) &&
                    d.points.every(
                      (p: { time: number; price: number }) =>
                        p &&
                        Number.isFinite(p.time) &&
                        Number.isFinite(p.price) &&
                        p.price > 0,
                    ) &&
                    (d.kind !== "trend" || d.points[0].time < d.points[1].time),
                )
                .slice(0, 50)
            : [],
        );
        localStorage.setItem("freya-trading-session", state.id);
      } catch {
        setDrawings([]);
      }
      window.history.replaceState(null, "", `/trading?session=${state.id}`);
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
    const id =
      new URLSearchParams(window.location.search).get("session") ||
      localStorage.getItem("freya-trading-session");
    if (id)
      void api(`/sessions/${id}`, undefined, controller.signal)
        .then((state) => {
          if (!controller.signal.aborted) accept(state, true);
        })
        .then(() => api(`/analysis/${id}`, undefined, controller.signal))
        .then((r) => {
          if (!controller.signal.aborted && current.current?.id === id)
            setReport(r);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
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
      const id = (event as CustomEvent).detail.session_id;
      if (id === current.current?.id)
        void refresh(id).catch((e) => setError(e.message));
    };
    window.addEventListener("freya-trading", handler);
    return () => window.removeEventListener("freya-trading", handler);
  }, [refresh]);
  useEffect(
    () => () => {
      analysisAbort.current?.abort();
      guideAbort.current?.abort();
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
        active: document.visibilityState === "visible" && document.hasFocus(),
      }).catch(() => {});
    };
    sync();
    const timer = setInterval(sync, 30000);
    window.addEventListener("focus", sync);
    window.addEventListener("blur", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", sync);
      window.removeEventListener("blur", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [s?.id, panel, selected]); // eslint-disable-line react-hooks/exhaustive-deps
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
    guideAbort.current?.abort();
    await run(async () => {
      const body = { key: crypto.randomUUID(), symbol, interval, mode };
      const state = await api(
        source === "sample"
          ? "/sessions"
          : source === "observation"
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
  async function ask(text = question) {
    if (!s || guideBusy || text.trim().length < 3) return;
    setPlaying(false);
    setQuestion("");
    setGuideBusy(true);
    setError("");
    const id = s.id;
    const controller = new AbortController();
    guideAbort.current = controller;
    try {
      const reply = await api(
        `/guide/${id}`,
        { question: text, provider: guideProvider, candle_id: selected },
        controller.signal,
      );
      if (current.current?.id === id)
        setMessages((prev) => [...prev, { question: text, reply }].slice(-20));
    } catch (e) {
      if (!controller.signal.aborted)
        setError(e instanceof Error ? e.message : "Guide unavailable");
    } finally {
      setGuideBusy(false);
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
  const change =
    last && previous ? (+last.close / +previous.close - 1) * 100 : 0;
  const pending = s?.orders.filter((o) => o.status === "pending") ?? [];
  const currentReport = report && report.snapshot?.id === s?.id;
  const refPrice = kind === "limit" ? +price : +(last?.close ?? 0);
  const notional = +quantity * refPrice;
  const estimatedFee = notional * +(s?.fee ?? 0);
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
          <button className="subtle" onClick={() => setSideTab("guide")}>
            ✧ Ask Freya
          </button>
        </div>
      </header>
      <section className="market-bar">
        <div className="market-title">
          <span className="coin-icon">
            {(s?.symbol ?? symbol).startsWith("BTC") ? "B" : "Ξ"}
          </span>
          <div>
            <h1>
              {s?.symbol ?? symbol}
              <span>
                {s?.interval ? s.interval / 60 : interval / 60}m · SPOT
              </span>
            </h1>
            <small>{s?.source ?? "Choose a market to begin"}</small>
          </div>
        </div>
        <div className="market-price">
          <strong>{last ? money(last.close) : "—"}</strong>
          <span className={change >= 0 ? "positive" : "negative"}>
            {change >= 0 ? "+" : ""}
            {change.toFixed(2)}% <small>last bar</small>
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
      {error && (
        <div role="alert" className="workspace-error">
          {error}
          <button aria-label="Dismiss error" onClick={() => setError("")}>
            ×
          </button>
        </div>
      )}
      <div className="workspace-grid">
        <aside className="market-sidebar">
          <div className="section-heading">
            MARKETS <span>2 instruments</span>
          </div>
          {["BTC-USD", "ETH-USD"].map((ticker) => (
            <button
              key={ticker}
              className={`market-row ${symbol === ticker ? "active" : ""}`}
              onClick={() => setSymbol(ticker)}
            >
              <span className="small-coin">
                {ticker.startsWith("BTC") ? "B" : "Ξ"}
              </span>
              <span>
                <b>{ticker}</b>
                <small>
                  {ticker.startsWith("BTC") ? "Bitcoin" : "Ethereum"}
                </small>
              </span>
              {s?.symbol === ticker && (
                <span className="market-row-price">
                  {last ? num(last.close) : "—"}
                </span>
              )}
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
                <option value="sample">Sample replay</option>
                <option value="historical">Coinbase history</option>
                <option value="observation">Current observation</option>
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
              onClick={() => {
                setSideTab("guide");
                void ask("How do I start?");
              }}
              disabled={!s}
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
          <div className="chart-stage">
            <nav className="drawing-toolbar" aria-label="Drawing tools">
              {(
                [
                  ["cursor", "↖", "Crosshair"],
                  ["level", "―", "Horizontal level"],
                  ["trend", "╱", "Trendline"],
                ] as const
              ).map(([value, icon, label]) => (
                <button
                  key={value}
                  title={label}
                  aria-label={label}
                  aria-pressed={tool === value}
                  onClick={() => setTool(value)}
                >
                  {icon}
                </button>
              ))}
              <span />
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
              <small>{drawings.length}/50</small>
            </nav>
            {s ? (
              <Chart
                key={s.id}
                session={s}
                report={report}
                options={options}
                tool={tool}
                drawings={drawings}
                selected={selected}
                onSelect={setSelected}
                onDraw={(d) => {
                  if (drawings.length < 50) saveDrawings([...drawings, d]);
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
              {s?.environment === "observation" ? "OBSERVATION" : "BAR REPLAY"}
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
                  Poll closed candles ↻
                </button>
                <span className={s.feed_stale ? "negative" : "positive"}>
                  {s.feed_stale ? "Stale feed" : "Latest fetched candle"} ·
                  manual polling
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
            {[
              ["Virtual equity", s ? money(s.equity) : "$10,000.00"],
              ["Available cash", s ? money(+s.cash - +s.reserved_cash) : "—"],
              [
                "Position",
                s ? `${num(s.quantity)} ${s.symbol.split("-")[0]}` : "—",
              ],
              ["Fees paid", s ? money(s.fees) : "—"],
              ["Max drawdown", s ? `${(+s.drawdown * 100).toFixed(2)}%` : "—"],
            ].map(([label, value]) => (
              <div key={label}>
                <small>{label}</small>
                <strong>{value}</strong>
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
                        <th>Mark price</th>
                        <th>Market value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s && (
                        <tr>
                          <td>{s.symbol}</td>
                          <td>{num(s.quantity)}</td>
                          <td>{num(s.reserved_quantity)}</td>
                          <td>{money(last!.close)}</td>
                          <td>{money(+s.quantity * +last!.close)}</td>
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
                      <a href={`/trading?session=${j.session}`}>
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
              ✧ Freya guide
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
                  Ask about this workspace, a candle, or your paper account.
                  I’ll use the data you can see.
                </p>
              </div>
              <div className="guide-context">
                <i />{" "}
                {s
                  ? `${s.symbol} · ${s.interval / 60}m · ${selected ? "selected candle" : "latest candle"}`
                  : "Open a session to begin"}
              </div>
              <div className="quick-questions">
                {[
                  "Explain this candle",
                  "Why is my order pending?",
                  "What does RSI mean?",
                  "Explain my available cash",
                ].map((q) => (
                  <button
                    key={q}
                    disabled={!s || guideBusy}
                    onClick={() => ask(q)}
                  >
                    {q} <span>↗</span>
                  </button>
                ))}
              </div>
              <div className="guide-messages" aria-live="polite">
                {messages.map((m, i) => (
                  <div key={i}>
                    <p className="user-question">{m.question}</p>
                    <p className="guide-answer">{m.reply.answer}</p>
                    <small>
                      {m.reply.provider === "local"
                        ? "Quick help · no API call"
                        : `Gemini · ${m.reply.tokens ?? "unknown"} tokens`}
                      {m.reply.revision !== s?.revision
                        ? " · historical snapshot"
                        : ""}
                    </small>
                  </div>
                ))}
                {guideBusy && (
                  <p className="muted">Freya is reading your snapshot…</p>
                )}
              </div>
              <form
                className="guide-compose"
                onSubmit={(e) => {
                  e.preventDefault();
                  void ask();
                }}
              >
                <select
                  aria-label="Guide mode"
                  value={guideProvider}
                  onChange={(e) => setGuideProvider(e.target.value)}
                >
                  <option value="local">Quick help · free</option>
                  <option value="gemini">Gemini · custom question</option>
                </select>
                <textarea
                  aria-label="Ask Freya"
                  placeholder="What would you like to understand?"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                />
                <button
                  className="primary full"
                  disabled={!s || guideBusy || question.trim().length < 3}
                >
                  Ask Freya ↗
                </button>
                {guideBusy && (
                  <button
                    type="button"
                    onClick={() => guideAbort.current?.abort()}
                  >
                    Cancel
                  </button>
                )}
              </form>
              <p className="muted">
                Voice: ask Freya about the Trading Lab. Keep this tab focused so
                she can read its context directly.
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
