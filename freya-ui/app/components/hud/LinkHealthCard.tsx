"use client";

import { useState, useSyncExternalStore } from "react";
import { CLOSE_CODES, type LinkError, type LinkStats } from "../../hooks/useFreyaSocket";
import HudCard from "./HudCard";

const SOURCE_LABEL: Record<LinkError["source"], string> = {
  socket: "SOCKET",
  ping: "PING",
  session: "GEMINI",
};

const OK = "var(--accent-red)";
const WARN = "#f5b642";
const BAD = "#ff5c5c";

// A 1 s wall clock so "open for" / "last msg" ages tick without setState loops.
let cachedNow = 0;
const subscribe = (cb: () => void) => {
  const id = setInterval(cb, 1000);
  return () => clearInterval(id);
};
const getNow = () => {
  const n = Math.floor(Date.now() / 1000) * 1000;
  if (n !== cachedNow) cachedNow = n;
  return cachedNow;
};

function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const clock = (d: Date) => d.toLocaleTimeString([], { hour12: false });

function Row({ label, value, color, title }: { label: string; value: string; color?: string; title?: string }) {
  return (
    <div className="flex items-center justify-between gap-2" title={title}>
      <span className="text-[9px] tracking-[0.18em] uppercase" style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}>
        {label}
      </span>
      <span className="text-[10px] font-mono truncate" style={{ color: color ?? "var(--text-primary)" }}>
        {value}
      </span>
    </div>
  );
}

/** Bar per ping: height = latency, red = no reply. */
function PingSpark({ history }: { history: (number | null)[] }) {
  const max = Math.max(100, ...history.map((v) => v ?? 0));
  return (
    <div className="flex items-end gap-[2px] h-6 mt-1" aria-label="Ping history">
      {Array.from({ length: 30 }, (_, i) => {
        const v = history[i - (30 - history.length)];
        if (v === undefined) return <span key={i} className="flex-1 h-[2px] opacity-20" style={{ background: "var(--text-tertiary)" }} />;
        return (
          <span
            key={i}
            className="flex-1 rounded-[1px]"
            title={v === null ? "no reply" : `${v} ms`}
            style={{
              height: v === null ? "100%" : `${Math.max(8, (v / max) * 100)}%`,
              background: v === null ? BAD : v > 250 ? WARN : OK,
              opacity: v === null ? 0.8 : 0.7,
            }}
          />
        );
      })}
    </div>
  );
}

/**
 * Left column, bottom: health of the dashboard ↔ server.py link.
 * Ping statistics over the last 30 checks (5 s apart), the WebSocket's state
 * and traffic, and a log of every socket / ping / Gemini Live error with a
 * hint on what to check. Click an error to expand it.
 */
export default function LinkHealthCard({
  connected,
  stats,
  pingMs,
  errors,
  onClear,
}: {
  connected: boolean;
  stats: LinkStats;
  pingMs: number | null;
  errors: LinkError[];
  onClear: () => void;
}) {
  const now = useSyncExternalStore(subscribe, getNow, () => 0);
  const [open, setOpen] = useState<number | null>(null);

  const replies = stats.pingHistory.filter((v): v is number => v !== null);
  const loss = stats.pingHistory.length
    ? Math.round(((stats.pingHistory.length - replies.length) / stats.pingHistory.length) * 100)
    : 0;
  const avg = replies.length ? Math.round(replies.reduce((a, b) => a + b, 0) / replies.length) : null;
  const jitter =
    replies.length > 1
      ? Math.round(replies.slice(1).reduce((a, v, i) => a + Math.abs(v - replies[i]), 0) / (replies.length - 1))
      : null;

  const overall = !connected || pingMs === null ? "DOWN" : loss > 0 || (pingMs ?? 0) > 250 ? "DEGRADED" : "HEALTHY";
  const overallColor = overall === "HEALTHY" ? OK : overall === "DEGRADED" ? WARN : BAD;
  const silentFor = stats.lastMessageAt && now ? now - stats.lastMessageAt : null;

  return (
    <HudCard
      title="Link Health"
      right={
        <span className="text-[9px] font-mono tracking-[0.2em]" style={{ color: overallColor }}>
          ● {overall}
        </span>
      }
    >
      <div className="flex flex-col gap-1.5">
        {/* Ping */}
        <Row
          label="Ping /status"
          value={pingMs === null ? "NO REPLY" : `${pingMs} ms`}
          color={pingMs === null ? BAD : pingMs > 250 ? WARN : OK}
        />
        <Row
          label="Avg · Min · Max"
          value={replies.length ? `${avg} · ${Math.min(...replies)} · ${Math.max(...replies)} ms` : "—"}
        />
        <Row label="Jitter · Loss" value={`${jitter ?? "—"} ms · ${loss}%`} color={loss > 0 ? WARN : undefined}
          title={`${stats.pingHistory.length - replies.length} of the last ${stats.pingHistory.length} pings got no reply`} />
        <PingSpark history={stats.pingHistory} />

        <div className="h-px my-1 opacity-30" style={{ background: "var(--accent-red-dim)" }} />

        {/* WebSocket */}
        <Row
          label="WebSocket"
          value={
            connected
              ? `OPEN · ${stats.socketOpenedAt && now ? ago(now - stats.socketOpenedAt) : "0s"}`
              : `CLOSED · retry #${stats.reconnectAttempts}`
          }
          color={connected ? OK : BAD}
          title="ws://localhost:8000/ws"
        />
        <Row
          label="Msgs · Last"
          value={`${stats.messagesReceived} · ${silentFor === null ? "—" : `${ago(silentFor)} ago`}`}
        />
        <Row
          label="Connects · Last close"
          value={`${stats.connects} · ${stats.lastClose ? `${stats.lastClose.code}` : "—"}`}
          title={stats.lastClose ? `${CLOSE_CODES[stats.lastClose.code] ?? "Unknown"} at ${clock(new Date(stats.lastClose.at))}` : undefined}
        />

        <div className="h-px my-1 opacity-30" style={{ background: "var(--accent-red-dim)" }} />

        {/* Error log */}
        <div className="flex items-center justify-between">
          <span className="text-[9px] tracking-[0.18em] uppercase" style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}>
            Errors ({errors.length})
          </span>
          {errors.length > 0 && (
            <button
              onClick={onClear}
              className="text-[9px] tracking-[0.2em] uppercase opacity-60 hover:opacity-100 transition-opacity"
              style={{ color: "var(--text-tertiary)", fontFamily: "var(--font-ui)" }}
            >
              Clear
            </button>
          )}
        </div>
        {errors.length === 0 ? (
          <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>No errors since page load</p>
        ) : (
          <ul className="flex flex-col gap-1 max-h-40 overflow-y-auto pr-1">
            {[...errors].reverse().map((e) => {
              const expanded = open === e.id;
              return (
                <li key={e.id}>
                  <button
                    onClick={() => setOpen(expanded ? null : e.id)}
                    className="w-full text-left rounded px-1.5 py-1 transition-colors hover:bg-white/5"
                    style={{ borderLeft: `2px solid ${e.source === "session" ? BAD : WARN}` }}
                  >
                    <div className="flex items-center gap-2 text-[9px] font-mono">
                      <span style={{ color: "var(--text-tertiary)" }}>{clock(e.timestamp)}</span>
                      <span style={{ color: e.source === "session" ? BAD : WARN }}>{SOURCE_LABEL[e.source]}</span>
                      {e.count > 1 && <span style={{ color: "var(--text-tertiary)" }}>×{e.count}</span>}
                    </div>
                    <p className={`text-[10px] font-mono leading-snug break-words ${expanded ? "" : "line-clamp-2"}`}
                      style={{ color: "var(--text-primary)" }}>
                      {e.message}
                    </p>
                    {expanded && (
                      <div className="mt-1 text-[10px] leading-snug" style={{ color: "var(--text-secondary, var(--text-tertiary))" }}>
                        {e.hint && <p>→ {e.hint}</p>}
                        {e.count > 1 && (
                          <p className="font-mono opacity-70 mt-0.5">
                            First {clock(e.firstSeen)} · last {clock(e.timestamp)}
                          </p>
                        )}
                      </div>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </HudCard>
  );
}
