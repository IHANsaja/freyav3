export type DrawingKind =
  | "trend"
  | "ray"
  | "extended"
  | "arrow"
  | "hline"
  | "hray"
  | "vline"
  | "cross"
  | "channel"
  | "pitchfork"
  | "fib"
  | "fibext"
  | "rect"
  | "ellipse"
  | "triangle"
  | "brush"
  | "text"
  | "long"
  | "short"
  | "pricerange"
  | "daterange"
  | "datepricerange";
export type ChartTool = "cursor" | "eraser" | DrawingKind;
export type Point = { time: number; price: number };
export type Drawing = {
  id: string;
  kind: DrawingKind;
  points: Point[];
  text?: string;
  /** "freya" when Freya drew it by voice; absent/"user" for the user's own. */
  author?: "user" | "freya";
};

/** points = clicks needed; 0 = freehand drag. */
export const TOOLS: Record<
  DrawingKind,
  { label: string; icon: string; points: number }
> = {
  trend: { label: "Trend line", icon: "╱", points: 2 },
  ray: { label: "Ray", icon: "↗", points: 2 },
  extended: { label: "Extended line", icon: "⤢", points: 2 },
  arrow: { label: "Arrow", icon: "➚", points: 2 },
  hline: { label: "Horizontal line", icon: "―", points: 1 },
  hray: { label: "Horizontal ray", icon: "⟶", points: 1 },
  vline: { label: "Vertical line", icon: "│", points: 1 },
  cross: { label: "Cross line", icon: "┼", points: 1 },
  channel: { label: "Parallel channel", icon: "▱", points: 3 },
  pitchfork: { label: "Pitchfork", icon: "⋔", points: 3 },
  fib: { label: "Fib retracement", icon: "≣", points: 2 },
  fibext: { label: "Trend-based fib extension", icon: "☰", points: 3 },
  rect: { label: "Rectangle", icon: "▭", points: 2 },
  ellipse: { label: "Ellipse", icon: "◯", points: 2 },
  triangle: { label: "Triangle", icon: "△", points: 3 },
  brush: { label: "Brush", icon: "✎", points: 0 },
  text: { label: "Text", icon: "T", points: 1 },
  long: { label: "Long position", icon: "⇡", points: 2 },
  short: { label: "Short position", icon: "⇣", points: 2 },
  pricerange: { label: "Price range", icon: "↕", points: 2 },
  daterange: { label: "Date range", icon: "↔", points: 2 },
  datepricerange: { label: "Date & price range", icon: "⤡", points: 2 },
};

export const TOOL_GROUPS: { id: string; label: string; tools: ChartTool[] }[] = [
  { id: "cursor", label: "Crosshair", tools: ["cursor"] },
  {
    id: "lines",
    label: "Lines",
    tools: ["trend", "ray", "extended", "arrow", "hline", "hray", "vline", "cross"],
  },
  { id: "channels", label: "Channels & pitchforks", tools: ["channel", "pitchfork"] },
  { id: "fib", label: "Fibonacci", tools: ["fib", "fibext"] },
  { id: "shapes", label: "Shapes & brush", tools: ["rect", "ellipse", "triangle", "brush"] },
  { id: "text", label: "Text", tools: ["text"] },
  { id: "projection", label: "Positions", tools: ["long", "short"] },
  { id: "measure", label: "Measure", tools: ["pricerange", "daterange", "datepricerange"] },
  { id: "eraser", label: "Eraser", tools: ["eraser"] },
];

export const toolIcon = (tool: ChartTool) =>
  tool === "cursor" ? "✛" : tool === "eraser" ? "⌫" : TOOLS[tool].icon;
export const toolLabel = (tool: ChartTool) =>
  tool === "cursor" ? "Crosshair" : tool === "eraser" ? "Eraser" : TOOLS[tool].label;

export const MAX_DRAWINGS = 200;

/** Compact, size-bounded copy of the drawings for Freya's workspace context. */
export const drawingSummary = (drawings: Drawing[]) =>
  drawings.map((d) => ({
    id: d.id.slice(0, 64),
    kind: d.kind,
    author: d.author ?? "user",
    text: d.text?.slice(0, 200),
    point_count: d.points.length,
    points: (d.kind === "brush"
      ? [d.points[0], d.points[d.points.length - 1]]
      : d.points
    ).map((p) => ({ time: Math.round(p.time), price: p.price })),
  }));
export const MAX_BRUSH_POINTS = 500;

export function isDrawing(value: unknown): value is Drawing {
  if (!value || typeof value !== "object") return false;
  const d = value as Drawing;
  if (typeof d.id !== "string" || !Object.hasOwn(TOOLS, d.kind)) return false;
  if (!Array.isArray(d.points)) return false;
  const need = TOOLS[d.kind].points;
  const n = d.points.length;
  if (need ? n !== need : n < 2 || n > MAX_BRUSH_POINTS) return false;
  if (d.text !== undefined && (typeof d.text !== "string" || d.text.length > 500))
    return false;
  if (d.author !== undefined && d.author !== "user" && d.author !== "freya")
    return false;
  return d.points.every(
    (p) => p && Number.isFinite(p.time) && Number.isFinite(p.price) && p.price > 0,
  );
}
