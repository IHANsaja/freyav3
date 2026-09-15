"use client";
import { useEffect, useState } from "react";
type Feed = {
  items: {
    title: string;
    url: string;
    source: string;
    published_at: number;
    symbols: string[];
    macro: boolean;
    stale: boolean;
  }[];
  sources: {
    source: string;
    fetched_at: number | null;
    stale: boolean;
    error: string | null;
  }[];
  checked_at: number;
  cache_seconds: number;
};
export default function NewsPanel({
  symbol,
  replay,
}: {
  symbol: string;
  replay: boolean;
}) {
  const [allow, setAllow] = useState(!replay);
  const [filter, setFilter] = useState("ALL");
  const [feed, setFeed] = useState<Feed | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!allow) return;
    const abort = new AbortController();
    async function load() {
      setBusy(true);
      try {
        const r = await fetch(
          `http://localhost:8000/trading/news?symbol=${encodeURIComponent(filter)}`,
          { signal: abort.signal },
        );
        if (!r.ok)
          throw Error(
            "News is unavailable. Retry later or open the publisher directly.",
          );
        const data = await r.json();
        if (!abort.signal.aborted) {
          setFeed(data);
          setError("");
        }
      } catch (e) {
        if (!abort.signal.aborted)
          setError(e instanceof Error ? e.message : "News unavailable");
      } finally {
        if (!abort.signal.aborted) setBusy(false);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 300000);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, [allow, filter, refresh]);
  return (
    <section className="learning-panel">
      <h2>Market news</h2>
      <p className="muted">
        Headlines, publication times and original sources. Read the full story
        and compare sources before forming a view.
      </p>
      {replay && (
        <div className="news-notice">
          Today’s news is outside this replay’s timeline. It must not be used as
          evidence for a past trade.
          {!allow && (
            <button className="subtle" onClick={() => setAllow(true)}>
              Show today’s news
            </button>
          )}
        </div>
      )}
      {allow && (
        <>
          <div className="news-controls">
            <select
              aria-label="News filter"
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setFeed(null);
              }}
            >
              <option value="ALL">All finance & crypto</option>
              <option value={symbol.split("-")[0]}>
                {symbol.split("-")[0]} + central bank news
              </option>
            </select>
            <button disabled={busy} onClick={() => setRefresh((n) => n + 1)}>
              {busy ? "Loading headlines…" : "Refresh news"}
            </button>
          </div>
          <p className="muted">
            Five-minute shared cache · no Gemini calls ·{" "}
            {feed
              ? `checked ${new Date(feed.checked_at * 1000).toLocaleTimeString()}`
              : "waiting for sources"}
          </p>
          {error && <p role="alert">{error}</p>}
          {feed?.sources.map((s) => (
            <p key={s.source} className={s.stale ? "negative" : "muted"}>
              {s.source}: {s.error ?? "feed retrieved"}
              {s.stale ? " · cached headlines may be outdated" : ""}
              {s.fetched_at
                ? ` · fetched ${new Date(s.fetched_at * 1000).toLocaleString()}`
                : ""}
            </p>
          ))}
          <div className="news-list">
            {feed?.items.map((item) => (
              <article key={item.url}>
                <small>
                  {item.source} ·{" "}
                  <time
                    dateTime={new Date(item.published_at * 1000).toISOString()}
                  >
                    {new Date(item.published_at * 1000).toLocaleString()}
                  </time>
                  {item.stale ? " · STALE CACHE" : ""}
                </small>
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title} ↗
                </a>
                <span>
                  {item.macro
                    ? "Central bank / macro"
                    : item.symbols.join(" · ") || "Crypto markets"}
                </span>
              </article>
            ))}
          </div>
          {feed && !feed.items.length && (
            <p>
              No dated headlines match this filter. No substitute headlines have
              been generated.
            </p>
          )}
        </>
      )}
    </section>
  );
}
