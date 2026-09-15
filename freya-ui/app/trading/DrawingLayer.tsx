"use client";
import type { ReactNode } from "react";
import {
  TOOLS,
  type Drawing,
  type DrawingKind,
  type Point,
} from "./drawingTools";

export type Frame = {
  w: number;
  h: number;
  interval: number;
  toX: (time: number) => number | null;
  toY: (price: number) => number | null;
};
type XY = [number, number];

const BLUE = "#759aff";
const GREEN = "#21baa0";
const RED = "#ef6474";
const FIB_COLORS = [
  "#ef6474",
  "#d5ad68",
  "#21baa0",
  "#6d99ff",
  "#21baa0",
  "#d5ad68",
  "#b197ff",
];

const fmt = (n: number) =>
  n.toLocaleString(undefined, {
    maximumFractionDigits: Math.abs(n) < 10 ? 5 : 2,
  });
function far(a: XY, b: XY, k = 10000): XY {
  const dx = b[0] - a[0],
    dy = b[1] - a[1],
    l = Math.hypot(dx, dy) || 1;
  return [b[0] + (dx / l) * k, b[1] + (dy / l) * k];
}
function duration(seconds: number) {
  const s = Math.abs(seconds);
  const d = Math.floor(s / 86400),
    h = Math.floor((s % 86400) / 3600),
    m = Math.floor((s % 3600) / 60);
  return `${d ? `${d}d ` : ""}${h ? `${h}h ` : ""}${m}m`;
}
const baseLine = (a: XY, b: XY, color = BLUE, extra: object = {}) => (
  <line
    x1={a[0]}
    y1={a[1]}
    x2={b[0]}
    y2={b[1]}
    stroke={color}
    strokeWidth={2}
    {...extra}
  />
);
const baseLabel = (
  x: number,
  y: number,
  text: string,
  color = BLUE,
  anchor: "start" | "middle" | "end" = "start",
) => (
  <text
    x={x}
    y={y}
    fill={color}
    fontSize={10}
    textAnchor={anchor}
    paintOrder="stroke"
    stroke="#10151f"
    strokeWidth={3}
  >
    {text}
  </text>
);
const box = (a: XY, b: XY, fill: string, stroke = "none") => (
  <rect
    x={Math.min(a[0], b[0])}
    y={Math.min(a[1], b[1])}
    width={Math.abs(b[0] - a[0])}
    height={Math.abs(b[1] - a[1])}
    fill={fill}
    stroke={stroke}
  />
);
const poly = (pts: XY[]) => pts.map((p) => p.join(",")).join(" ");

function shape(
  kind: DrawingKind,
  points: Point[],
  f: Frame,
  text?: string,
  appearance?: Drawing,
): ReactNode {
  const BLUE = appearance?.color ?? "#759aff";
  const line = (a: XY, b: XY, color = BLUE, extra: object = {}) =>
    baseLine(a, b, color, { strokeWidth: appearance?.width ?? 2, ...extra });
  const label = (
    x: number,
    y: number,
    text: string,
    color = BLUE,
    anchor: "start" | "middle" | "end" = "start",
  ) => baseLabel(x, y, text, color, anchor);
  const projected = points.map((p) => {
    const x = f.toX(p.time),
      y = f.toY(p.price);
    return x === null || y === null ? null : ([x, y] as XY);
  });
  if (projected.some((p) => p === null)) return null;
  const q = projected as XY[];
  const need = TOOLS[kind].points;
  if (need && q.length < need)
    return q.length > 1 ? (
      <polyline
        points={poly(q)}
        fill="none"
        stroke={BLUE}
        strokeWidth={appearance?.width ?? 2}
        strokeDasharray="4 3"
      />
    ) : null;
  const [a, b, c] = q;
  switch (kind) {
    case "trend":
      return line(a, b);
    case "arrow":
      return line(a, b, BLUE, { markerEnd: "url(#drawing-arrow)" });
    case "ray":
      return line(a, far(a, b));
    case "extended":
      return line(far(b, a), far(a, b));
    case "hline":
      return (
        <>
          {line([0, a[1]], [f.w, a[1]])}
          {label(f.w - 4, a[1] - 4, fmt(points[0].price), BLUE, "end")}
        </>
      );
    case "hray":
      return (
        <>
          {line(a, [f.w, a[1]])}
          {label(a[0] + 4, a[1] - 4, fmt(points[0].price))}
        </>
      );
    case "vline":
      return line([a[0], 0], [a[0], f.h]);
    case "cross":
      return (
        <>
          {line([0, a[1]], [f.w, a[1]])}
          {line([a[0], 0], [a[0], f.h])}
        </>
      );
    case "rect":
      return box(a, b, `${BLUE}22`, BLUE);
    case "ellipse":
      return (
        <ellipse
          cx={(a[0] + b[0]) / 2}
          cy={(a[1] + b[1]) / 2}
          rx={Math.abs(b[0] - a[0]) / 2}
          ry={Math.abs(b[1] - a[1]) / 2}
          fill={`${BLUE}22`}
          stroke={BLUE}
          strokeWidth={appearance?.width ?? 2}
        />
      );
    case "triangle":
      return (
        <polygon
          points={poly(q)}
          fill={`${BLUE}22`}
          stroke={BLUE}
          strokeWidth={appearance?.width ?? 2}
        />
      );
    case "brush":
      return (
        <polyline
          points={poly(q)}
          fill="none"
          stroke={BLUE}
          strokeWidth={appearance?.width ?? 2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      );
    case "text":
      return (
        <text
          x={a[0]}
          y={a[1]}
          fill="#e6edf7"
          fontSize={13}
          paintOrder="stroke"
          stroke="#10151f"
          strokeWidth={3}
        >
          {text}
        </text>
      );
    case "channel": {
      const dx = b[0] - a[0] || 1;
      const off = c[1] - (a[1] + ((b[1] - a[1]) * (c[0] - a[0])) / dx);
      const a2: XY = [a[0], a[1] + off],
        b2: XY = [b[0], b[1] + off];
      return (
        <>
          <polygon points={poly([a, b, b2, a2])} fill={`${BLUE}1a`} />
          {line(a, b)}
          {line(a2, b2)}
          {line([a[0], a[1] + off / 2], [b[0], b[1] + off / 2], BLUE, {
            strokeWidth: 1,
            strokeDasharray: "4 3",
          })}
        </>
      );
    }
    case "pitchfork": {
      const m: XY = [(b[0] + c[0]) / 2, (b[1] + c[1]) / 2];
      const d: XY = [m[0] - a[0], m[1] - a[1]];
      return (
        <>
          {line(a, far(a, m), "#d5ad68")}
          {line(b, far(b, [b[0] + d[0], b[1] + d[1]]))}
          {line(c, far(c, [c[0] + d[0], c[1] + d[1]]))}
          {line(b, c, BLUE, { strokeWidth: 1 })}
        </>
      );
    }
    case "fib": {
      const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
      const x1 = Math.min(a[0], b[0]),
        x2 = Math.max(a[0], b[0]);
      const from = points[0].price,
        to = points[1].price;
      return (
        <>
          {line(a, b, "#8391a8", { strokeWidth: 1, strokeDasharray: "4 3" })}
          {levels.map((l, i) => {
            const price = to - (to - from) * l;
            const y = f.toY(price);
            if (y === null) return null;
            return (
              <g key={l}>
                {line([x1, y], [x2, y], FIB_COLORS[i], { strokeWidth: 1 })}
                {label(
                  x1 - 4,
                  y + 3,
                  `${l} (${fmt(price)})`,
                  FIB_COLORS[i],
                  "end",
                )}
              </g>
            );
          })}
        </>
      );
    }
    case "fibfan": {
      const ratios = [0.382, 0.5, 0.618];
      return (
        <>
          {line(a, b, "#8391a8", { strokeWidth: 1, strokeDasharray: "4 3" })}
          {ratios.map((r) => {
            const end: XY = [b[0], a[1] + (b[1] - a[1]) * r];
            return (
              <g key={r}>
                {line(a, far(a, end))}
                {label(end[0] + 5, end[1], String(r))}
              </g>
            );
          })}
        </>
      );
    }
    case "fibext": {
      const levels = [0, 0.382, 0.618, 1, 1.618, 2.618];
      const move = points[1].price - points[0].price;
      const x2 = c[0] + Math.max(60, Math.abs(b[0] - a[0]));
      return (
        <>
          <polyline
            points={poly(q)}
            fill="none"
            stroke="#8391a8"
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          {levels.map((l, i) => {
            const price = points[2].price + move * l;
            const y = f.toY(price);
            if (y === null || price <= 0) return null;
            return (
              <g key={l}>
                {line([c[0], y], [x2, y], FIB_COLORS[i], { strokeWidth: 1 })}
                {label(x2 + 4, y + 3, `${l} (${fmt(price)})`, FIB_COLORS[i])}
              </g>
            );
          })}
        </>
      );
    }
    case "long":
    case "short": {
      const entry = points[0].price;
      const risk = Math.abs(entry - points[1].price) || entry * 0.005;
      const dir = kind === "long" ? 1 : -1;
      const ratio = appearance?.rewardRatio ?? 2;
      const target = entry + dir * ratio * risk,
        stop = entry - dir * risk;
      const yE = a[1],
        yT = f.toY(target),
        yS = f.toY(stop);
      if (yT === null || yS === null) return null;
      const x1 = a[0],
        x2 = b[0] > a[0] + 10 ? b[0] : a[0] + 120;
      const pct = (p: number) => (((p - entry) / entry) * 100).toFixed(2);
      return (
        <>
          {box([x1, yE], [x2, yT], `${GREEN}33`)}
          {box([x1, yE], [x2, yS], `${RED}33`)}
          {line([x1, yE], [x2, yE], "#e6edf7", { strokeWidth: 1 })}
          {label(
            x1 + 4,
            yT + (dir === 1 ? 12 : -4),
            `Target ${fmt(target)} (${pct(target)}%)`,
            GREEN,
          )}
          {label(
            x1 + 4,
            yS + (dir === 1 ? -4 : 12),
            `Stop ${fmt(stop)} (${pct(stop)}%)`,
            RED,
          )}
          {label(
            x2 - 4,
            yE - 4,
            `${kind === "long" ? "Long" : "Short"} · R:R ${ratio.toFixed(2)}`,
            "#e6edf7",
            "end",
          )}
        </>
      );
    }
    case "pricerange":
    case "daterange":
    case "datepricerange": {
      const dp = points[1].price - points[0].price;
      const bars = Math.round((points[1].time - points[0].time) / f.interval);
      const color = kind === "daterange" ? BLUE : dp >= 0 ? GREEN : RED;
      const parts = [
        kind !== "daterange" &&
          `${fmt(dp)} (${((dp / points[0].price) * 100).toFixed(2)}%)`,
        kind !== "pricerange" &&
          `${bars} bars, ${duration(points[1].time - points[0].time)}`,
      ].filter(Boolean);
      const cx = (a[0] + b[0]) / 2;
      return (
        <>
          {box(a, b, `${color}26`)}
          {kind !== "daterange" &&
            line([cx, a[1]], [cx, b[1]], color, {
              markerEnd: "url(#drawing-arrow)",
            })}
          {kind !== "pricerange" &&
            line([a[0], (a[1] + b[1]) / 2], [b[0], (a[1] + b[1]) / 2], color, {
              markerEnd: "url(#drawing-arrow)",
            })}
          {label(
            cx,
            Math.max(a[1], b[1]) + 14,
            parts.join(" · "),
            color,
            "middle",
          )}
        </>
      );
    }
  }
}

export default function DrawingLayer({
  frame,
  drawings,
  draft,
  eraser,
  onErase,
}: {
  frame: Frame;
  drawings: Drawing[];
  draft: { kind: DrawingKind; points: Point[] } | null;
  eraser: boolean;
  onErase: (id: string) => void;
}) {
  return (
    <svg
      className="drawing-layer"
      width={frame.w}
      height={frame.h}
      style={{ pointerEvents: "none" }}
    >
      <defs>
        <marker
          id="drawing-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
        </marker>
      </defs>
      {drawings
        .filter((d) => !d.hidden)
        .map((d) => (
          <g
            key={d.id}
            className={eraser && !d.locked ? "erasable" : undefined}
            style={{
              pointerEvents: eraser && !d.locked ? "visiblePainted" : "none",
              // Freya's drawings share the shapes but read as hers: violet, not blue.
              filter:
                d.author === "freya"
                  ? "hue-rotate(45deg) saturate(1.4)"
                  : undefined,
            }}
            onClick={eraser && !d.locked ? () => onErase(d.id) : undefined}
          >
            {d.author === "freya" && <title>Drawn by Freya</title>}
            {shape(d.kind, d.points, frame, d.text, d)}
          </g>
        ))}
      {draft && <g opacity={0.7}>{shape(draft.kind, draft.points, frame)}</g>}
    </svg>
  );
}
