"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import Chart from "./Chart";
import type { Session, Report } from "./types";
import { useSharedFreyaSocket } from "../components/FreyaSocketProvider";
const API = "http://localhost:8000/trading";
async function api(path: string, body?: unknown, signal?: AbortSignal) {
  const r = await fetch(API + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const result = await r.json();
  if (!r.ok)
    throw Error(
      typeof result.detail === "string"
        ? result.detail
        : "Request rejected; refresh and check inputs",
    );
  return result;
}
const money = (s: string | number) =>
  Number(s).toLocaleString(undefined, { style: "currency", currency: "USD" });
export default function TradingPage() {
  const { connected } = useSharedFreyaSocket();
  const analysisController = useRef<AbortController | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [followed, setFollowed] = useState(true);
  const [historyStart, setHistoryStart] = useState("2025-01-01");
  const [learning, setLearning] = useState<{review_count:number;followed_plan_count:number;analysis_count:number;known_ai_tokens:number;ai_cost_usd:string|null}|null>(null);
  const [s, setS] = useState<Session | null>(null),
    [report, setReport] = useState<Report | null>(null);
  const [tab, setTab] = useState("Practice"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [symbol, setSymbol] = useState("BTC-USD"),
    [interval, setIntervalValue] = useState(900),
    [mode, setMode] = useState("independent");
  const [thesis, setThesis] = useState(""),
    [invalidation, setInvalidation] = useState("");
  const [side, setSide] = useState("buy"),
    [kind, setKind] = useState("market"),
    [quantity, setQuantity] = useState("0.01"),
    [price, setPrice] = useState(""),
    [target, setTarget] = useState("");
  const [openaiAvailable, setOpenaiAvailable] = useState(false);
  const [provider, setProvider] = useState("gemini"),
    [image, setImage] = useState<string | null>(null);
  const [journal, setJournal] = useState<
    {
      id: number;
      session: string;
      action: string;
      as_of: number;
      note?: string;
      followed_plan?: boolean;
      thesis?: { text: string; invalidation: string };
    }[]
  >([]);
  const refresh = useCallback(async (id: string) => {
    const state: Session = await api(`/sessions/${id}`);
    setS(previous => previous && (previous.id !== id || previous.revision > state.revision) ? previous : state);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void api('/providers', undefined, controller.signal)
      .then(result => setOpenaiAvailable(result.openai === true))
      .catch(() => {});
    return () => controller.abort();
  }, [connected]);
  useEffect(() => {
    const id =
      new URLSearchParams(window.location.search).get("session") ||
      localStorage.getItem("freya-trading-session");
    if (id) {
      const controller = new AbortController();
      void api(`/analysis/${id}`, undefined, controller.signal)
        .then(setReport)
        .catch(() => {});
      void api(`/sessions/${id}`, undefined, controller.signal)
        .then(state => {setS(state);setError("");})
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
      return () => controller.abort();
    }
  }, [refresh, connected]);
  useEffect(() => {
    if (!s) return;
    const id = s.id;
    const listener = (event: Event) => {
      const detail=(event as CustomEvent<import('../types/events').TradingEventPayload>).detail;
      if(detail.session_id!==id)return;
      void refresh(id).catch((e) => setError(e.message));
    };
    window.addEventListener("freya-trading", listener);
    return () => window.removeEventListener("freya-trading", listener);
  }, [s?.id, refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  async function observe() {
    await run(async () => {
      const state = await api("/observation", {
        key: crypto.randomUUID(),
        symbol,
        interval,
        mode,
      });
      setS(state);
      setReport(null);
      localStorage.setItem("freya-trading-session", state.id);
      window.history.replaceState(null,"",`/trading?session=${state.id}`);
    });
  }
  async function historical() {
    await run(async () => {
      const start = Date.parse(historyStart) / 1000;
      const state = await api("/historical", {
        key: crypto.randomUUID(),
        symbol,
        interval,
        mode,
        start,
        end: start + interval * 500,
      });
      setS(state);
      setReport(null);
      localStorage.setItem("freya-trading-session", state.id);
      window.history.replaceState(null,"",`/trading?session=${state.id}`);
    });
  }
  async function create() {
    await run(async () => {
      const state = await api("/sessions", {
        key: crypto.randomUUID(),
        symbol,
        interval,
        mode,
      });
      setS(state);
      setReport(null);
      localStorage.setItem("freya-trading-session", state.id);
      window.history.replaceState(null,"",`/trading?session=${state.id}`);
    });
  }
  async function mutate(action: string, body: object) {
    if (!s) return;
    await run(async () => {
      setS(
        await api(`/sessions/${s.id}/${action}`, {
          key: crypto.randomUUID(),
          revision: s.revision,
          ...body,
        }),
      );
    });
  }
  async function analyze() {
    if (!s) return;
    await run(async () => {
      analysisController.current = new AbortController();
      setReport(
        await api(
          `/analysis/${s.id}`,
          { provider, image_base64: image },
          analysisController.current.signal,
        ),
      );
      setTab("Analyst Desk");
    });
  }
  const input =
    "w-full rounded border border-white/15 bg-[#17171d] px-3 py-2 text-sm";
  const button =
    "rounded border border-rose-300/25 bg-rose-400/10 px-4 py-2 text-sm text-rose-100 disabled:opacity-40 hover:bg-rose-400/20";
  const panel = "rounded-xl border border-white/10 bg-[#101014] p-5";
  const latest = s?.indicators.at(-1);
  return (
    <main className="min-h-screen bg-[#09090d] text-zinc-200 p-5 md:p-9">
      <div className="max-w-7xl mx-auto space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs tracking-[.25em] text-rose-300">
              FREYA / LEARNING SYSTEMS
            </p>
            <h1 className="text-3xl mt-2">Trading Lab</h1>
            <p className="text-sm text-zinc-400 mt-2">
              Practice a decision. Observe its consequences. Keep the evidence.
            </p>
          </div>
          <span className="text-xs border border-amber-300/25 text-amber-200 rounded-full px-4 py-2">
            SIMULATED · No actual earnings
          </span>
        </header>
        <div className="flex flex-wrap gap-2">
          {["Practice", "Analyst Desk", "Journal", "Progress"].map((t) => (
            <button
              className={`${button} ${tab === t ? "ring-1 ring-rose-300" : ""}`}
              key={t}
              onClick={() => {
                setTab(t);
                if(t === "Progress" && s) void run(async()=>setLearning(await api(`/progress/${s.id}`)));
                if (t === "Journal")
                  void run(async () => setJournal(await api("/journal")));
              }}
            >
              {t}
            </button>
          ))}
        </div>
        {error && (
          <p
            role="alert"
            className="border border-red-400/40 p-4 rounded text-red-200"
          >
            {error}
          </p>
        )}
        <section className={`${panel} flex flex-wrap gap-3 items-end`}>
          <label>
            Market
            <select
              className={input}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              <option>BTC-USD</option>
              <option>ETH-USD</option>
            </select>
          </label>
          <label>
            Timeframe
            <select
              className={input}
              value={interval}
              onChange={(e) => setIntervalValue(+e.target.value)}
            >
              <option value={900}>15 minutes</option>
              <option value={3600}>1 hour</option>
            </select>
          </label>
          <label>
            Practice style
            <select
              className={input}
              value={mode}
              onChange={(e) => setMode(e.target.value)}
            >
              <option value="independent">Independent · thesis first</option>
              <option value="coached">Coached</option>
            </select>
          </label>
          <button className={button} disabled={busy} onClick={create}>
            {s ? "New session / reset" : "Start sample replay"}
          </button>
          <p className="text-xs text-zinc-500">
            $10,000 virtual cash. Reset retains your journal.
          </p>
          <button className={button} disabled={busy} onClick={observe}>
            Current market observation
          </button>
          <label className="text-xs">
            Historical start
            <input
              type="date"
              className={input}
              value={historyStart}
              onChange={(e) => setHistoryStart(e.target.value)}
            />
          </label>
          <button className={button} disabled={busy} onClick={historical}>
            Load Coinbase history
          </button>
        </section>
        {s && (
          <>
            {s.environment === "observation" && (
              <section className={panel}>
                <p>
                  Current market observation · separate virtual account · manual
                  polling, not streaming ·{" "}
                  {s.feed_stale
                    ? "STALE FEED"
                    : "latest closed candle available"}
                </p>
                <button
                  className={button}
                  disabled={busy}
                  onClick={() =>
                    run(async () =>
                      setS(await api(`/observation/${s.id}/poll`, {})),
                    )
                  }
                >
                  Poll / reconnect and backfill
                </button>
              </section>
            )}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                ["Virtual equity", money(s.equity)],
                ["Available cash", money(+s.cash - +s.reserved_cash)],
                ["Spot position", `${s.quantity} ${s.symbol.split("-")[0]}`],
                ["Fees paid", money(s.fees)],
              ].map(([a, b]) => (
                <div key={a} className={panel}>
                  <p className="text-xs text-zinc-400">{a}</p>
                  <p className="text-xl mt-2">{b}</p>
                </div>
              ))}
            </section>
            {tab === "Practice" && (
              <div className="grid lg:grid-cols-[1fr_320px] gap-5">
                <section className={panel}>
                  <div className="flex justify-between gap-3">
                    <h2>
                      {s.symbol} · {s.interval / 60}m
                    </h2>
                    <span className="text-xs text-amber-200">{s.source}</span>
                  </div>
                  <Chart session={s} report={report} />
                  <div className="flex flex-wrap gap-5 text-xs text-zinc-400 mt-4">
                    <span>
                      EMA 20: {latest?.ema?.toFixed(2) ?? "warming up"}
                    </span>
                    <span>
                      RSI 14: {latest?.rsi?.toFixed(1) ?? "warming up"}
                    </span>
                    <span>
                      ATR 14: {latest?.atr?.toFixed(2) ?? "warming up"}
                    </span>
                  </div>
                  <div className="flex gap-3 mt-5">
                    <button
                      className={button}
                      disabled={
                        busy || s.finished || s.environment === "observation"
                      }
                      onClick={() => mutate("advance", { bars: 1 })}
                    >
                      Advance 1 candle →
                    </button>
                    <button
                      className={button}
                      disabled={
                        busy || s.finished || s.environment === "observation"
                      }
                      onClick={() => mutate("advance", { bars: 10 })}
                    >
                      +10
                    </button>
                    <span className="text-xs self-center">
                      {new Date(s.candles.at(-1)!.time * 1000).toUTCString()}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 mt-3">
                    Next-open market fills · {(Number(s.fee) * 100).toFixed(2)}%
                    fee · {(Number(s.slippage) * 100).toFixed(2)}% slippage ·
                    full fills only · stop first on ambiguous candles
                  </p>
                </section>
                <aside className={`${panel} space-y-3`}>
                  <h2>Record your decision</h2>
                  <label className="block text-xs">
                    Thesis
                    <textarea
                      className={input}
                      value={thesis}
                      onChange={(e) => setThesis(e.target.value)}
                      placeholder="What do you see, and what would you expect next?"
                    />
                  </label>
                  <label className="block text-xs">
                    Invalidation
                    <input
                      className={input}
                      value={invalidation}
                      onChange={(e) => setInvalidation(e.target.value)}
                      placeholder="What evidence would change your mind?"
                    />
                  </label>
                  <button
                    className={button}
                    disabled={
                      busy ||
                      thesis.trim().length < 5 ||
                      invalidation.trim().length < 3
                    }
                    onClick={() => mutate("thesis", { thesis, invalidation })}
                  >
                    Save thesis
                  </button>
                  {s.thesis && (
                    <p className="text-xs text-emerald-300">
                      Recorded: {s.thesis.text}
                    </p>
                  )}
                  <hr className="border-white/10" />
                  <div className="flex gap-2">
                    <select
                      aria-label="Side"
                      className={input}
                      value={side}
                      onChange={(e) => setSide(e.target.value)}
                    >
                      <option value="buy">Buy</option>
                      <option value="sell">Sell</option>
                    </select>
                    <select
                      aria-label="Order type"
                      className={input}
                      value={kind}
                      onChange={(e) => setKind(e.target.value)}
                    >
                      {["market", "limit", "stop", "bracket"].map((k) => (
                        <option key={k}>{k}</option>
                      ))}
                    </select>
                  </div>
                  <label className="block text-xs">
                    Quantity
                    <input
                      className={input}
                      value={quantity}
                      onChange={(e) => setQuantity(e.target.value)}
                    />
                  </label>
                  {kind !== "market" && (
                    <label className="block text-xs">
                      Limit / stop price
                      <input
                        className={input}
                        value={price}
                        onChange={(e) => setPrice(e.target.value)}
                      />
                    </label>
                  )}
                  {kind === "bracket" && (
                    <label className="block text-xs">
                      Target
                      <input
                        className={input}
                        value={target}
                        onChange={(e) => setTarget(e.target.value)}
                      />
                    </label>
                  )}
                  <p className="text-xs text-zinc-400">
                    Reference notional:{" "}
                    {money(+quantity * +(price || s.candles.at(-1)!.close))}.
                    Gaps can change the fill; unaffordable orders are rejected.
                  </p>
                  <button
                    className={button}
                    disabled={busy || !s.thesis}
                    onClick={() =>
                      mutate("order", {
                        side,
                        kind,
                        quantity,
                        ...(kind !== "market" ? { price } : {}),
                        ...(kind === "bracket" ? { target } : {}),
                      })
                    }
                  >
                    Submit virtual order
                  </button>
                </aside>
              </div>
            )}
            {tab === "Practice" && (
              <section className={panel}>
                <h2>Orders & fills</h2>
                <div className="space-y-2 mt-3">
                  {s.orders.length === 0 && (
                    <p className="text-zinc-500 text-sm">
                      No orders yet. Save a thesis to begin.
                    </p>
                  )}
                  {s.orders.map((o) => (
                    <div
                      className="flex justify-between text-sm border-b border-white/5 py-2"
                      key={o.id}
                    >
                      <span>
                        {o.side} {o.quantity} · {o.kind} · {o.status}
                      </span>
                      {o.status === "pending" && (
                        <button
                          disabled={busy}
                          onClick={() => mutate("cancel", { order_id: o.id })}
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  ))}
                  {s.fills.map((f) => (
                    <p className="text-sm text-zinc-400" key={f.order_id}>
                      Filled {f.quantity} at {money(f.price)} · fee{" "}
                      {money(f.fee)}{" "}
                      {f.ambiguous ? "· Ambiguous candle: stop first" : ""}
                    </p>
                  ))}
                </div>
              </section>
            )}
            {(tab === "Practice" || tab === "Analyst Desk") && (
              <section className={`${panel} space-y-4`}>
                <h2>Ask Freya to explain the recorded decision</h2>
                <div className="flex flex-wrap gap-3">
                  <select
                    aria-label="Analysis provider"
                    className={input + " max-w-64"}
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                  >
                    <option value="offline">Offline lesson · no AI cost</option>
                    <option value="gemini">
                      Gemini · backend key required
                    </option>
                    {openaiAvailable && <option value="openai">
                      OpenAI · backend key required
                    </option>}
                  </select>
                  <button
                    disabled={busy || (!s.thesis && s.mode === "independent")}
                    className={button}
                    onClick={analyze}
                  >
                    {busy ? "Working…" : "Explain decision"}
                  </button>
                  {busy && (
                    <button
                      className={button}
                      onClick={() => analysisController.current?.abort()}
                    >
                      Cancel analysis
                    </button>
                  )}
                  <label className="text-xs">
                    Optional chart image (PNG/JPEG, 2 MB)
                    <input
                      type="file"
                      accept="image/png,image/jpeg"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (!f) {
                          setImage(null);
                          return;
                        }
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
                </div>
                {report && (
                  <>
                    <p className="text-xs text-amber-200">
                      {report.revision !== s.revision
                        ? "STALE · Replay or decision has advanced"
                        : "As-of current revision"}{" "}
                      · {report.provider} · {report.usage.model} · tokens{" "}
                      {report.usage.tokens ?? "unavailable"} · cost{" "}
                      {report.usage.cost_usd === null
                        ? "unavailable"
                        : money(report.usage.cost_usd)}{" "}
                      {report.veto ? "· RISK VETO" : ""}
                    </p>
                    <div className="grid md:grid-cols-3 gap-3">
                      {report.stages.map((stage) => (
                        <div
                          key={stage.name}
                          className="border border-white/10 rounded p-4"
                        >
                          <h3 className="text-rose-200">
                            {stage.name} · {stage.status}
                          </h3>
                          <p className="text-sm my-2">{stage.finding}</p>
                          <p className="text-xs text-zinc-500">
                            {stage.duration_ms} ms
                          </p>
                        </div>
                      ))}
                    </div>
                    {report.error && <p role="alert">{report.error}</p>}
                    {report.analysis && (
                      <div className="space-y-3">
                        <h3>Observations with evidence</h3>
                        {report.analysis.observations.map((o, i) => (
                          <p key={i} className="text-sm">
                            {o.text}
                            <span className="block text-xs text-zinc-500">
                              Candles: {o.evidence.join(", ")}
                            </span>
                          </p>
                        ))}
                        <p>
                          Interpretation / bullish: {report.analysis.bullish}
                        </p>
                        <p>
                          Interpretation / bearish: {report.analysis.bearish}
                        </p>
                        <p>Invalidation: {report.analysis.invalidation}</p>
                        <p className="text-rose-200">
                          Lesson: {report.analysis.lesson}
                        </p>
                      </div>
                    )}
                    <details className="text-xs">
                      <summary>Inspect snapshot and audit</summary>
                      <pre className="overflow-auto max-h-80">
                        {JSON.stringify(report, null, 2)}
                      </pre>
                    </details>
                  </>
                )}
              </section>
            )}
            {tab === "Progress" && (
              <section className={`${panel} space-y-4`}>
                <h2>Learning progress</h2>
                {learning && <p>Reviewed decisions: {learning.review_count} · Followed plan: {learning.followed_plan_count} (self-assessed) · Analyses: {learning.analysis_count} · Reported AI tokens: {learning.known_ai_tokens} · AI cost: {learning.ai_cost_usd===null?"unavailable":money(learning.ai_cost_usd)}</p>}
                <label className="block">
                  Decision review
                  <textarea
                    className={input}
                    value={reviewNote}
                    onChange={(e) => setReviewNote(e.target.value)}
                    placeholder="Did your recorded invalidation guide your actions?"
                  />
                </label>
                <label className="block">
                  <input
                    type="checkbox"
                    checked={followed}
                    onChange={(e) => setFollowed(e.target.checked)}
                  />{" "}
                  I followed my recorded plan (self-assessment)
                </label>
                <button
                  className={button}
                  disabled={busy || reviewNote.trim().length < 5}
                  onClick={() =>
                    run(async () => {
                      await api(`/review/${s.id}`, {
                        key: crypto.randomUUID(),
                        note: reviewNote,
                        followed_plan: followed,
                      });
                      setReviewNote("");
                    })
                  }
                >
                  Save review to journal
                </button>
                <p>Fill sample size: {s.sample_size}</p>
                <p>
                  Maximum observed equity drawdown:{" "}
                  {(Number(s.drawdown) * 100).toFixed(2)}%
                </p>
                <p>
                  Fees: {money(s.fees)} · Virtual result:{" "}
                  {money(+s.equity - 10000)}
                </p>
                <p>
                  Every order requires a thesis. Review whether your actual
                  decision followed its invalidation; no score rewards frequent
                  trading.
                </p>
                <p className="text-zinc-500">
                  Small synthetic samples do not establish strategy performance.
                  AI usage is reported separately in Analyst Desk.
                </p>
              </section>
            )}
          </>
        )}
        {tab === "Journal" && (
          <section className={`${panel} space-y-4`}>
            <h2>Saved decision journal · all sessions</h2>
            {journal.map((e) => (
              <article key={e.id} className="border-b border-white/10 py-3">
                <p>
                  {e.action} · {new Date(e.as_of * 1000).toUTCString()}
                </p>
                {e.thesis && (
                  <p className="text-sm text-zinc-400">
                    {e.thesis.text} · Invalidation: {e.thesis.invalidation}
                  </p>
                )}
                <a
                  className="text-xs text-zinc-500 underline"
                  href={`/trading?session=${e.session}`}
                >
                  Session {e.session}
                </a>
                {e.note && (
                  <p>
                    {e.note} · Followed plan: {e.followed_plan ? "yes" : "no"}{" "}
                    (self-reported)
                  </p>
                )}
              </article>
            ))}
          </section>
        )}
      </div>
    </main>
  );
}
