"use client";

import { useEffect, useRef, useState } from "react";
import type {
  ActivityPayload,
  ActivityPhase,
  ActivityRecent,
  HealthPayload,
  ToolCategory,
} from "../types/events";

/**
 * The header's live "what is she doing" readout.
 *
 * One line in the header — a rune for the phase or tool kind, the sentence
 * from the backend's activity feed, a running timer, and chips for anything
 * else in flight. Click it for the tool-usage log: every recent call with its
 * outcome and duration, plus session totals.
 *
 * Each phase and tool kind carries the Elder Futhark rune whose meaning fits it
 * (Kenaz, the torch, for searching; Fehu, wealth, for trading; Hagalaz, the
 * hailstorm, for a dropped link), so the glyph alone reads at a glance.
 */

export const PHASE_RUNE: Record<ActivityPhase | "offline" | "error", { rune: string; name: string }> = {
  idle: { rune: "ᛁ", name: "Isa — stillness" },
  listening: { rune: "ᛚ", name: "Laguz — flow" },
  hearing: { rune: "ᛚ", name: "Laguz — flow" },
  thinking: { rune: "ᛜ", name: "Ingwaz — gestation" },
  speaking: { rune: "ᚨ", name: "Ansuz — the voice" },
  working: { rune: "ᚱ", name: "Raidho — the journey" },
  approval: { rune: "ᚾ", name: "Nauthiz — need" },
  recovering: { rune: "ᚺ", name: "Hagalaz — the storm" },
  offline: { rune: "ᛁ", name: "Isa — frozen" },
  error: { rune: "ᚦ", name: "Thurisaz — the thorn" },
};

export const CATEGORY_RUNE: Record<ToolCategory, { rune: string; kind: string }> = {
  search: { rune: "ᚲ", kind: "Search" },
  file: { rune: "ᛈ", kind: "Files" },
  app: { rune: "ᛗ", kind: "Apps" },
  screen: { rune: "ᛞ", kind: "Screen" },
  system: { rune: "ᛏ", kind: "System" },
  web: { rune: "ᚱ", kind: "Web" },
  memory: { rune: "ᛟ", kind: "Memory" },
  agent: { rune: "ᛖ", kind: "Agents" },
  trading: { rune: "ᚠ", kind: "Trading" },
  display: { rune: "ᛊ", kind: "Display" },
  other: { rune: "ᛃ", kind: "Other" },
};

const STATUS_STYLE: Record<ActivityRecent["status"], { mark: string; color: string; word: string }> = {
  ok: { mark: "✓", color: "var(--accent-green)", word: "done" },
  error: { mark: "✕", color: "var(--accent-red-dim)", word: "failed" },
  timeout: { mark: "◷", color: "#e0a33a", word: "timed out" },
  resting: { mark: "∥", color: "#e0a33a", word: "resting" },
};

const THINK_AFTER_MS = 800;

function fmtDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
  return `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`;
}

interface Props {
  activity: ActivityPayload | null;
  health?: HealthPayload | null;
  connected: boolean;
  running: boolean;
}

export default function ActivityIndicator({ activity, health, connected, running }: Props) {
  const [now, setNow] = useState(() => Date.now());
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Tick only while something is timed: running tools or an unanswered turn.
  // Fast while something is being timed, slow otherwise (a failure mark still
  // has to expire, and a stale clock would pin it on screen).
  const timed = !!activity && (activity.tools.length > 0 || activity.phase === "hearing");
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), timed ? 250 : 1000);
    return () => clearInterval(id);
  }, [timed]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // ── What to say ──
  let phase: ActivityPhase | "offline" = activity?.phase ?? "idle";
  let label = activity?.label ?? "Standing by";
  let started: number | null = null;
  const lead = activity?.tools.at(-1);
  if (!connected) {
    phase = "offline";
    label = "Backend offline — reconnecting";
  } else if (!running && phase !== "recovering") {
    phase = "idle";
    label = "Standing by";
  } else if (phase === "hearing" && activity?.heardAt) {
    const since = now - activity.heardAt * 1000;
    if (since > THINK_AFTER_MS) {
      phase = "thinking";
      label = "Thinking";
      started = activity.heardAt * 1000 + THINK_AFTER_MS;
    }
  } else if (phase === "working" && lead) {
    started = lead.startedAt * 1000;
  }
  if (connected && health?.overall === "down" && phase !== "recovering") {
    const live = health.components.find((c) => c.name === "live" && c.state === "down");
    if (live) {
      phase = "recovering";
      label = live.detail || "Voice link down";
    }
  }

  const rune =
    phase === "working" && lead ? CATEGORY_RUNE[lead.category]?.rune ?? PHASE_RUNE.working.rune : PHASE_RUNE[phase].rune;
  const elapsed = started ? now - started : 0;
  const busy = phase === "working" || phase === "thinking" || phase === "hearing" || phase === "speaking";
  const warn = phase === "approval" || phase === "recovering";
  const tone = !connected || phase === "offline"
    ? "var(--text-tertiary)"
    : warn
      ? "#e0a33a"
      : "var(--accent-red)";
  const others = (activity?.tools.length ?? 0) - 1;
  const background = lead?.mode === "background";
  const recent = activity?.recent ?? [];
  const lastFail = recent[0] && recent[0].status !== "ok" && now / 1000 - recent[0].endedAt < 4 ? recent[0] : null;

  return (
    <div ref={rootRef} className="relative min-w-0 flex-1 flex justify-center px-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`Freyja activity: ${label}. Show tool usage.`}
        title="What Freyja is doing — click for tool usage"
        className="activity-pill group flex items-center gap-2.5 h-9 max-w-[560px] min-w-0 pl-2 pr-3 border transition-colors duration-300"
        data-phase={phase}
        style={{
          borderColor: warn ? "rgba(224,163,58,0.45)" : "var(--panel-border)",
          borderRadius: "999px",
          background: "rgba(5,8,7,0.55)",
          boxShadow: busy ? `0 0 18px -6px ${tone}` : "none",
        }}
      >
        <span
          aria-hidden
          className={`rune-glyph flex items-center justify-center w-6 h-6 rounded-full text-[15px] leading-none ${busy || warn ? "rune-charged" : ""}`}
          style={{ color: tone, fontFamily: "var(--font-rune)", border: `1px solid ${tone}` }}
          title={phase === "working" && lead ? CATEGORY_RUNE[lead.category]?.kind : PHASE_RUNE[phase].name}
        >
          {rune}
        </span>
        <span
          className="truncate text-[12px] tracking-[0.06em]"
          style={{ fontFamily: "var(--font-ui)", color: "var(--text-primary)", fontWeight: 600 }}
        >
          {label}
          {busy && elapsed < 3000 && <span className="activity-dots" aria-hidden />}
        </span>
        {background && (
          <span className="shrink-0 text-[9px] font-mono uppercase tracking-[0.15em] px-1.5 py-0.5 rounded" style={{ color: tone, border: `1px solid ${tone}55` }}>
            bg
          </span>
        )}
        {others > 0 && (
          <span className="shrink-0 text-[10px] font-mono" style={{ color: "var(--text-secondary)" }}>
            +{others}
          </span>
        )}
        {elapsed >= 3000 && (
          <span className="shrink-0 text-[10px] font-mono tabular-nums" style={{ color: "var(--text-secondary)" }}>
            {fmtDuration(Math.round(elapsed))}
          </span>
        )}
        {lastFail && (
          <span
            className="shrink-0 text-[10px] font-mono"
            style={{ color: STATUS_STYLE[lastFail.status].color }}
            title={`${lastFail.label} ${STATUS_STYLE[lastFail.status].word}: ${lastFail.detail}`}
          >
            {STATUS_STYLE[lastFail.status].mark} {lastFail.name}
          </span>
        )}
        {(activity?.stats.calls ?? 0) > 0 && (
          <span className="shrink-0 hidden lg:inline text-[9px] font-mono uppercase tracking-[0.15em]" style={{ color: "var(--text-tertiary)" }}>
            {activity!.stats.calls} tools
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Tool usage"
          className="absolute top-11 w-[min(460px,92vw)] z-50 border p-3 text-[11px]"
          style={{
            borderColor: "var(--panel-border)",
            borderRadius: "10px",
            background: "rgba(6,9,8,0.94)",
            backdropFilter: "blur(12px)",
            color: "var(--text-secondary)",
          }}
        >
          <div className="flex items-center justify-between mb-2 font-mono uppercase tracking-[0.15em] text-[9px]">
            <span style={{ color: "var(--accent-red)" }}>ᚱ Tool usage</span>
            <span>
              {activity?.stats.calls ?? 0} calls · {activity?.stats.failures ?? 0} failed ·{" "}
              {fmtDuration(activity?.stats.tool_ms ?? 0)} total
            </span>
          </div>

          {activity && activity.tools.length > 0 && (
            <ul className="mb-2 space-y-1">
              {activity.tools.map((t) => (
                <li key={t.id} className="flex items-center gap-2">
                  <span className="rune-charged" style={{ fontFamily: "var(--font-rune)", color: "var(--accent-red)" }}>
                    {CATEGORY_RUNE[t.category]?.rune ?? "ᛃ"}
                  </span>
                  <span className="truncate flex-1" style={{ color: "var(--text-primary)" }}>{t.label}</span>
                  <span className="font-mono text-[9px] uppercase">{t.mode === "foreground" ? "running" : t.mode}</span>
                  <span className="font-mono tabular-nums">{fmtDuration(Math.max(0, now - t.startedAt * 1000))}</span>
                </li>
              ))}
            </ul>
          )}

          {recent.length === 0 ? (
            <p className="py-3 text-center" style={{ color: "var(--text-tertiary)" }}>
              No tools used yet this session.
            </p>
          ) : (
            <ul className="space-y-1 max-h-[280px] overflow-y-auto pr-1">
              {recent.map((r) => {
                const st = STATUS_STYLE[r.status] ?? STATUS_STYLE.ok;
                return (
                  <li key={`${r.id}-${r.endedAt}`} className="flex items-center gap-2" title={r.detail || undefined}>
                    <span style={{ fontFamily: "var(--font-rune)", color: "var(--text-tertiary)" }}>
                      {CATEGORY_RUNE[r.category]?.rune ?? "ᛃ"}
                    </span>
                    <span className="truncate flex-1">
                      <span style={{ color: "var(--text-primary)" }}>{r.label}</span>
                      <span className="ml-1.5 font-mono text-[9px]" style={{ color: "var(--text-tertiary)" }}>{r.name}</span>
                    </span>
                    <span className="font-mono tabular-nums">{fmtDuration(r.ms)}</span>
                    <span className="w-4 text-center" style={{ color: st.color }} aria-label={st.word}>
                      {st.mark}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}

          {health && health.overall !== "ok" && (
            <div className="mt-2 pt-2 border-t space-y-0.5" style={{ borderColor: "var(--panel-border)" }}>
              {health.components
                .filter((c) => c.state !== "ok")
                .map((c) => (
                  <div key={c.name} className="flex gap-2">
                    <span style={{ fontFamily: "var(--font-rune)", color: "#e0a33a" }}>ᚺ</span>
                    <span className="font-mono uppercase text-[9px] tracking-[0.12em] w-14">{c.name}</span>
                    <span className="flex-1">{c.detail || c.state}</span>
                  </div>
                ))}
              {health.resting_tools.length > 0 && (
                <div className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                  Resting: {health.resting_tools.join(", ")}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
