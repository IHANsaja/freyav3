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

// Fixed, non-overlapping anchor slots (3 per side, generously spaced so a
// ~250px-wide, up to ~260px-tall card never touches its neighbor). Cards are
// assigned a slot by their position in the sorted projection list — NOT by
// independent random placement — so concurrent projections can never stack on
// top of each other regardless of how many happen to hash close together.
const LEFT_SLOTS: { x: number; y: number }[] = [
  { x: 0.15, y: 0.20 },
  { x: 0.10, y: 0.48 },
  { x: 0.16, y: 0.76 },
];
const RIGHT_SLOTS: { x: number; y: number }[] = [
  { x: 0.85, y: 0.20 },
  { x: 0.90, y: 0.48 },
  { x: 0.84, y: 0.76 },
];

// slotIndex: this projection's position among CURRENTLY VISIBLE ones (0-based).
// Alternates left/right; small seeded jitter keeps it feeling organic without
// risking a collision (slots are ~0.28 apart vertically, jitter is +/-0.015).
function place(seed: number, slotIndex: number) {
  const slots = slotIndex % 2 === 0 ? LEFT_SLOTS : RIGHT_SLOTS;
  const slot = slots[Math.floor(slotIndex / 2) % slots.length];
  const r = mulberry32(seed);
  const jitterX = (r() - 0.5) * 0.03;
  const jitterY = (r() - 0.5) * 0.03;
  return { x: clamp(slot.x + jitterX, 0.06, 0.94), y: clamp(slot.y + jitterY, 0.14, 0.82) };
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

  // Positions computed ONCE per render and reused for both the beam SVG and
  // the card divs, so a beam always points exactly at its own card and both
  // loops agree on the same collision-free slot assignment.
  const placed = projections.map((p, i) => ({ p, pos: place(hashStr(p.key), i) }));

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
          {placed.map(({ p, pos }) => {
            const ax = pos.x * size.w;
            const ay = pos.y * size.h;
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
      {placed.map(({ p, pos: { x, y } }) => {
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
