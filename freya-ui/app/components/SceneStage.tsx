"use client";

import { useEffect, useRef, useState, ReactNode } from "react";
import { ToolEntry, ImageEntry, NewsItem } from "../hooks/useFreyaSocket";
import LiveFigure from "./LiveFigure";

/**
 * The dynamic "projection field". Every output Freya produces — world-news headlines (with
 * scraped images + live animated figures), screen captures, and other tool activity — is
 * scattered at varied positions around the central AI globe, and an energy BEAM connects the
 * globe to each one, so it reads like the globe is projecting / manipulating them on screen.
 * Projections fade after a TTL so the scene stays alive and uncluttered.
 */

const TTL = 16000; // ms a projection stays on screen
const MAX = 6;     // max concurrent projections

// ── tiny seeded PRNG so each item keeps a stable scatter position ──
function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function mulberry32(a: number) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// stable scatter: offset from center, clear of the globe + header + dock
function place(seed: number) {
  const r = mulberry32(seed);
  const side = r() < 0.5 ? -1 : 1;
  const x = 0.5 + side * (0.27 + r() * 0.12); // -> ~0.11–0.39 or 0.61–0.89
  const y = 0.17 + r() * 0.60;                // -> 0.17–0.77
  return { x: clamp(x, 0.09, 0.91), y: clamp(y, 0.15, 0.80) };
}

// wrap numbers inside a headline with animated LiveFigures
function renderHeadline(title: string): ReactNode[] {
  return title.split(/(\d[\d,]*\.?\d*%?)/g).map((p, i) => {
    if (/^\d/.test(p)) {
      const suffix = p.endsWith("%") ? "%" : "";
      const val = parseFloat(p.replace(/,/g, "").replace("%", ""));
      if (!isNaN(val)) return <LiveFigure key={i} value={val} suffix={suffix} />;
    }
    return <span key={i}>{p}</span>;
  });
}

type Proj = {
  key: string;
  kind: "news" | "image" | "tool";
  ts: number;
  news?: NewsItem;
  image?: ImageEntry;
  tool?: ToolEntry;
};

const TOOL_ICON: Record<string, string> = {
  get_weather: "🌦️", read_screen_elements: "🎯", find_element: "🎯",
  control_element: "🖱️", click_element: "🖱️", click_text: "🖱️",
  recall: "🧠", index_folder: "🧠", browser_task: "🌐",
  dispatch_agent: "🤖", schedule_task: "⏰", watch_screen: "👁️",
};

export default function SceneStage({
  toolLog,
  images,
  newsItems,
}: {
  toolLog: ToolEntry[];
  images: ImageEntry[];
  newsItems: NewsItem[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [now, setNow] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // tick "now" each second so TTL expiry re-evaluates (set only in async callbacks)
  useEffect(() => {
    const t0 = setTimeout(() => setNow(Date.now()), 0);
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearTimeout(t0);
      clearInterval(id);
    };
  }, []);
  const projections: Proj[] = [
    ...newsItems.map((n) => ({ key: `n${n.id}`, kind: "news" as const, ts: n.timestamp.getTime(), news: n })),
    ...images.map((i) => ({ key: `i${i.id}`, kind: "image" as const, ts: i.timestamp.getTime(), image: i })),
    ...toolLog
      .filter((t) => !["get_world_news", "get_news"].includes(t.name))
      .map((t) => ({ key: `t${t.id}`, kind: "tool" as const, ts: t.timestamp.getTime(), tool: t })),
  ]
    .filter((p) => now - p.ts < TTL)
    .sort((a, b) => b.ts - a.ts)
    .slice(0, MAX);

  const cx = size.w / 2;
  const cy = size.h / 2;

  return (
    <div ref={ref} className="absolute inset-0 pointer-events-none overflow-hidden">
      {/* Energy beams: globe (center) -> each projection */}
      {size.w > 0 && (
        <svg className="absolute inset-0 w-full h-full" style={{ zIndex: 6 }}>
          <defs>
            <linearGradient id="beamgrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#ffb3ac" stopOpacity="0.0" />
              <stop offset="40%" stopColor="#d32f2f" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#ffb3ac" stopOpacity="0.9" />
            </linearGradient>
          </defs>
          {projections.map((p) => {
            const { x, y } = place(hashStr(p.key));
            const ax = x * size.w;
            const ay = y * size.h;
            return (
              <g key={`beam-${p.key}`}>
                <line x1={cx} y1={cy} x2={ax} y2={ay}
                      stroke="#d32f2f" strokeWidth={4} opacity={0.10} />
                <line x1={cx} y1={cy} x2={ax} y2={ay}
                      stroke="url(#beamgrad)" strokeWidth={1.4}
                      strokeDasharray="3 7" className="beam-flow" opacity={0.8} />
                <circle cx={ax} cy={ay} r={3} fill="#ffb3ac" opacity={0.9} />
              </g>
            );
          })}
        </svg>
      )}

      {/* Projection panels */}
      {projections.map((p) => {
        const { x, y } = place(hashStr(p.key));
        return (
          <div
            key={p.key}
            className="projection absolute"
            style={{ left: `${x * 100}%`, top: `${y * 100}%`, transform: "translate(-50%,-50%)", zIndex: 10, width: 250 }}
          >
            {p.kind === "news" && p.news && <NewsCard item={p.news} />}
            {p.kind === "image" && p.image && <ImageCard item={p.image} />}
            {p.kind === "tool" && p.tool && <ToolCard item={p.tool} />}
          </div>
        );
      })}
    </div>
  );
}

const SHELL =
  "rounded-xl border border-primary/25 bg-surface-container-lowest/80 backdrop-blur-md " +
  "shadow-[0_8px_40px_rgba(0,0,0,0.55),0_0_24px_rgba(211,47,47,0.12)] overflow-hidden";

function NewsCard({ item }: { item: NewsItem }) {
  return (
    <div className={SHELL}>
      {item.image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={item.image}
          alt=""
          className="w-full h-28 object-cover border-b border-outline-variant/20"
          onError={(e) => (e.currentTarget.style.display = "none")}
        />
      )}
      <div className="p-3 flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest text-primary">
          <span className="w-1.5 h-1.5 rounded-full bg-primary live-dot" /> LIVE · WORLD NEWS
        </span>
        <p className="text-[12.5px] leading-snug text-parchment">{renderHeadline(item.title)}</p>
        {(item.source || item.logo) && (
          <span className="flex items-center gap-1.5 text-[9px] text-outline-variant uppercase tracking-wider">
            {item.logo && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.logo}
                alt=""
                className="w-3.5 h-3.5 rounded-sm"
                onError={(e) => (e.currentTarget.style.display = "none")}
              />
            )}
            {item.source}
          </span>
        )}
      </div>
    </div>
  );
}

function ImageCard({ item }: { item: ImageEntry }) {
  return (
    <div className={SHELL}>
      <div className="px-3 pt-2 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest text-primary">
        <span>👁</span> {item.label}
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`data:image/jpeg;base64,${item.data}`} alt={item.label} className="w-full mt-2" />
    </div>
  );
}

function ToolCard({ item }: { item: ToolEntry }) {
  const icon = TOOL_ICON[item.name.replace(/^⚡\s*/, "")] || "⚙️";
  return (
    <div className={`${SHELL} p-3 flex flex-col gap-1`}>
      <span className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest text-primary">
        <span className="text-sm">{icon}</span>
        {item.name.replace(/_/g, " ")}
      </span>
      <p className="text-[11px] leading-snug text-on-surface line-clamp-4">{item.result || "…"}</p>
    </div>
  );
}
