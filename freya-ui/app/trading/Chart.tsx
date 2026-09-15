"use client";
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  createSeriesMarkers,
  type Time,
  type ISeriesMarkersPluginApi,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
  type Logical,
} from "lightweight-charts";
import { visibleRange } from "./practiceMath";
import type { Session, Report, Candle } from "./types";
import DrawingLayer, { type Frame } from "./DrawingLayer";
import {
  TOOLS,
  MAX_BRUSH_POINTS,
  toolLabel,
  type ChartTool,
  type Drawing,
  type DrawingKind,
  type Point,
} from "./drawingTools";
export type { ChartTool, Drawing } from "./drawingTools";
export type ChartOptions = {
  ema: boolean;
  volume: boolean;
  rsi: boolean;
  line: boolean;
};
type Props = {
  session: Session;
  report: Report | null;
  options: ChartOptions;
  tool: ChartTool;
  drawings: Drawing[];
  onDraw: (d: Drawing) => void;
  onErase: (id: string) => void;
  onSelect: (id: string) => void;
  selected: string | null;
  fit: number;
  rangeSeconds: number | null;
  magnet: boolean;
  /** Still-forming live candle; drawn after the closed candles, never persisted. */
  liveCandle?: Candle | null;
};
export default function Chart(props: Props) {
  const root = useRef<HTMLDivElement>(null);
  const latest = useRef(props);
  const api = useRef<{
    chart: IChartApi;
    candles: ISeriesApi<"Candlestick">;
    close: ISeriesApi<"Line">;
    ema: ISeriesApi<"Line">;
    volume: ISeriesApi<"Histogram">;
    rsi: ISeriesApi<"Line">;
    markers: ISeriesMarkersPluginApi<Time>;
    redraw: () => void;
  } | null>(null);
  const [hover, setHover] = useState<Candle | null>(null);
  const [frame, setFrame] = useState<Frame | null>(null);
  type Draft = { kind: DrawingKind; points: Point[] };
  const draft = useRef<Draft | null>(null);
  const [draftView, setDraftView] = useState<Draft | null>(null);
  useEffect(() => {
    latest.current = props;
  }, [props]);
  useEffect(() => {
    const nav = props.tool === "cursor" || props.tool === "eraser";
    api.current?.chart.applyOptions({ handleScroll: nav, handleScale: nav });
  }, [props.tool]);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#10151f" },
        textColor: "#8391a8",
        attributionLogo: true,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1c2533" },
        horzLines: { color: "#1c2533" },
      },
      timeScale: { timeVisible: true, borderColor: "#263144", rightOffset: 5 },
      rightPriceScale: { borderColor: "#263144" },
      crosshair: {
        vertLine: { color: "#64748b", labelBackgroundColor: "#29354a" },
        horzLine: { color: "#64748b", labelBackgroundColor: "#29354a" },
      },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#21baa0",
      downColor: "#ef6474",
      wickUpColor: "#21baa0",
      wickDownColor: "#ef6474",
      borderVisible: false,
    });
    const close = chart.addSeries(LineSeries, {
      color: "#6d99ff",
      lineWidth: 2,
      visible: false,
    });
    const ema = chart.addSeries(LineSeries, {
      color: "#d5ad68",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const volume = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: "volume" },
        lastValueVisible: false,
        priceLineVisible: false,
      },
      1,
    );
    const rsi = chart.addSeries(
      LineSeries,
      { color: "#b197ff", lineWidth: 1, priceLineVisible: false },
      2,
    );
    [30, 70].forEach((price) =>
      rsi.createPriceLine({
        price,
        color: "#655480",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: String(price),
      }),
    );
    chart.panes()[0].setStretchFactor(5);
    chart.panes()[1].setStretchFactor(1);
    chart.panes()[2].setStretchFactor(1);
    // Drawings are stored as (time, price). Times beyond the loaded candles are
    // extrapolated on the candle interval so tools can extend into the future.
    const geometry = () => {
      const s = latest.current.session;
      const cs = s.candles;
      const last = cs.length - 1;
      return {
        cs,
        iv: s.interval,
        last,
        index: new Map(cs.map((c, i) => [c.time, i])),
        firstT: cs[0]?.time ?? 0,
        lastT: cs[last]?.time ?? 0,
      };
    };
    const toLogical = (t: number) => {
      const g = geometry();
      return (
        g.index.get(t) ??
        (t > g.lastT ? g.last + (t - g.lastT) / g.iv : (t - g.firstT) / g.iv)
      );
    };
    const pointAt = (x: number, y: number): Point | null => {
      const l = chart.timeScale().coordinateToLogical(x);
      const rawPrice = candles.coordinateToPrice(y);
      let price: number | null = rawPrice;
      if (l === null || price === null || price <= 0) return null;
      const g = geometry();
      const i = Math.round(l);
      const time =
        i >= 0 && i <= g.last
          ? g.cs[i].time
          : i > g.last
            ? g.lastT + (i - g.last) * g.iv
            : g.firstT + i * g.iv;
      if (
        latest.current.magnet &&
        latest.current.tool !== "cursor" &&
        i >= 0 &&
        i <= g.last
      ) {
        const c = g.cs[i];
        price = [+c.open, +c.high, +c.low, +c.close].reduce((a, b) =>
          Math.abs(b - Number(price)) < Math.abs(a - Number(price)) ? b : a,
        );
      }
      return { time, price: Number(price) };
    };
    let frameRequest = 0;
    const redraw = () => {
      cancelAnimationFrame(frameRequest);
      frameRequest = requestAnimationFrame(() => {
        const size = chart.paneSize(0);
        setFrame({
          w: size.width,
          h: size.height,
          interval: latest.current.session.interval,
          toX: (t) =>
            chart.timeScale().logicalToCoordinate(toLogical(t) as Logical),
          toY: (p) => candles.priceToCoordinate(p),
        });
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    chart.timeScale().subscribeSizeChange(redraw);
    api.current = {
      chart,
      candles,
      close,
      ema,
      volume,
      rsi,
      markers: createSeriesMarkers(candles, []),
      redraw,
    };
    chart.subscribeCrosshairMove((param) =>
      setHover(
        latest.current.session.candles.find((c) => c.time === param.time) ??
          null,
      ),
    );
    // Native pointer-up handles quick consecutive anchors that the chart's double-click filter suppresses.
    let down: { x: number; y: number; id: number } | null = null;
    let dragged = false;
    let brush: { points: Point[]; x: number; y: number } | null = null;
    const local = (e: PointerEvent) => {
      const bounds = el.getBoundingClientRect();
      return [e.clientX - bounds.left, e.clientY - bounds.top] as const;
    };
    const start = (e: PointerEvent) => {
      if (!e.isPrimary || e.button !== 0) {
        down = null;
        return;
      }
      down = { x: e.clientX, y: e.clientY, id: e.pointerId };
      dragged = false;
      if (latest.current.tool === "brush") {
        const [x, y] = local(e);
        const pt = pointAt(x, y);
        brush = pt ? { points: [pt], x, y } : null;
      }
    };
    const move = (e: PointerEvent) => {
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5)
        dragged = true;
      const [x, y] = local(e);
      if (brush) {
        if (Math.hypot(x - brush.x, y - brush.y) < 3) return;
        const pt = pointAt(x, y);
        if (!pt || brush.points.length >= MAX_BRUSH_POINTS) return;
        brush = { points: [...brush.points, pt], x, y };
        setDraftView({ kind: "brush", points: brush.points });
        return;
      }
      if (down && latest.current.tool === "cursor") redraw();
      const d = draft.current;
      if (d && d.kind === latest.current.tool) {
        const pt = pointAt(x, y);
        if (pt) setDraftView({ kind: d.kind, points: [...d.points, pt] });
      }
    };
    const finish = (e: PointerEvent) => {
      const anchor = down;
      down = null;
      const p = latest.current;
      if (brush) {
        const stroke = brush.points;
        brush = null;
        setDraftView(null);
        if (stroke.length >= 2)
          p.onDraw({ id: crypto.randomUUID(), kind: "brush", points: stroke });
        return;
      }
      if (
        !anchor ||
        anchor.id !== e.pointerId ||
        dragged ||
        Math.hypot(e.clientX - anchor.x, e.clientY - anchor.y) > 5
      )
        return;
      const [x, y] = local(e);
      const size = chart.paneSize(0);
      if (x < 0 || y < 0 || x >= size.width || y >= size.height) return;
      const point = pointAt(x, y);
      if (!point) return;
      const candle = p.session.candles.find((c) => c.time === point.time);
      if (candle) p.onSelect(candle.id);
      if (p.tool === "cursor" || p.tool === "eraser" || p.tool === "brush")
        return;
      const kind = p.tool;
      if (kind === "text") {
        const text = window.prompt("Text label")?.trim();
        if (text)
          p.onDraw({
            id: crypto.randomUUID(),
            kind,
            points: [point],
            text: text.slice(0, 500),
          });
        return;
      }
      const points = [
        ...(draft.current?.kind === kind ? draft.current.points : []),
        point,
      ];
      if (points.length >= TOOLS[kind].points) {
        p.onDraw({ id: crypto.randomUUID(), kind, points });
        draft.current = null;
        setDraftView(null);
      } else {
        draft.current = { kind, points };
        setDraftView({ kind, points });
      }
    };
    const cancel = () => {
      down = null;
      brush = null;
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      draft.current = null;
      brush = null;
      setDraftView(null);
    };
    el.addEventListener("pointerdown", start);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", finish);
    el.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", escape);
    return () => {
      el.removeEventListener("pointerdown", start);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", finish);
      el.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", escape);
      cancelAnimationFrame(frameRequest);
      chart.remove();
      api.current = null;
    };
  }, []);
  useEffect(() => {
    const a = api.current;
    if (!a) return;
    a.candles.setData(
      props.session.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: +c.open,
        high: +c.high,
        low: +c.low,
        close: +c.close,
      })),
    );
    a.close.setData(
      props.session.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        value: +c.close,
      })),
    );
    a.volume.setData(
      props.session.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        value: +c.volume,
        color: +c.close >= +c.open ? "#21baa066" : "#ef647466",
      })),
    );
    a.ema.setData(
      props.session.indicators
        .filter((i) => i.ema !== null)
        .map((i) => ({ time: i.time as UTCTimestamp, value: i.ema! })),
    );
    a.rsi.setData(
      props.session.indicators
        .filter((i) => i.rsi !== null)
        .map((i) => ({ time: i.time as UTCTimestamp, value: i.rsi! })),
    );
    a.redraw();
    a.markers.setMarkers(
      props.session.fills.map((f) => ({
        time: f.time as UTCTimestamp,
        position: f.side === "buy" ? "belowBar" : "aboveBar",
        color: f.side === "buy" ? "#21baa0" : "#ef6474",
        shape: f.side === "buy" ? "arrowUp" : "arrowDown",
        text: `${f.side} ${f.quantity}`,
      })),
    );
  }, [props.session]);
  useEffect(() => {
    const a = api.current;
    const c = props.liveCandle;
    const lastClosed = props.session.candles.at(-1);
    if (!a || !c || (lastClosed && c.time <= lastClosed.time)) return;
    const time = c.time as UTCTimestamp;
    a.candles.update({
      time,
      open: +c.open,
      high: +c.high,
      low: +c.low,
      close: +c.close,
    });
    a.close.update({ time, value: +c.close });
    a.volume.update({
      time,
      value: +c.volume,
      color: +c.close >= +c.open ? "#21baa066" : "#ef647466",
    });
  }, [props.liveCandle, props.session]);
  useEffect(() => {
    const a = api.current;
    if (!a) return;
    a.candles.applyOptions({ visible: !props.options.line });
    a.close.applyOptions({ visible: props.options.line });
    a.ema.applyOptions({ visible: props.options.ema });
    a.volume.applyOptions({ visible: props.options.volume });
    a.rsi.applyOptions({ visible: props.options.rsi });
    a.chart.panes()[1].setStretchFactor(props.options.volume ? 1 : 0.15);
    a.chart.panes()[2].setStretchFactor(props.options.rsi ? 1 : 0.15);
  }, [props.options]);
  useEffect(() => {
    api.current?.chart.timeScale().fitContent();
  }, [props.fit, props.session.id]);
  useEffect(() => {
    if (props.rangeSeconds === null) return;
    const range = visibleRange(
      props.session.candles.map((c) => c.time),
      props.session.interval,
      props.rangeSeconds,
    );
    if (range)
      api.current?.chart
        .timeScale()
        .setVisibleLogicalRange({ from: range.from, to: range.to });
  }, [props.rangeSeconds, props.session, props.fit]);
  useEffect(() => {
    const a = api.current;
    if (!a) return;
    const lines: IPriceLine[] = [];
    if (
      props.report?.revision === props.session.revision &&
      props.report.snapshot?.id === props.session.id
    )
      props.report.analysis?.zones.forEach((z) =>
        [z.low, z.high].forEach((price) =>
          lines.push(
            a.candles.createPriceLine({
              price: +price,
              color: "#b197ff",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: z.kind,
            }),
          ),
        ),
      );
    return () => {
      if (api.current !== a) return;
      lines.forEach((l) => a.candles.removePriceLine(l));
    };
  }, [props.report, props.session]);
  const activeDraft =
    draftView && draftView.kind === props.tool ? draftView : null;
  const need =
    props.tool === "cursor" || props.tool === "eraser"
      ? 0
      : TOOLS[props.tool].points;
  const hint =
    props.tool === "cursor"
      ? "Click a candle to give Freya its context"
      : props.tool === "eraser"
        ? "Eraser · click a drawing to remove it"
        : props.tool === "brush"
          ? "Brush · drag on the chart to draw"
          : `${toolLabel(props.tool)} · ${
              need > 1
                ? `click point ${Math.min(activeDraft?.points.length ?? 1, need)} of ${need}`
                : "click to place"
            } · Esc cancels`;
  const candle =
    hover ??
    props.session.candles.find((c) => c.id === props.selected) ??
    props.liveCandle ??
    props.session.candles.at(-1)!;
  return (
    <div className="chart-wrap">
      <div className="ohlc">
        <b>{props.session.symbol}</b>
        <span>{props.session.interval / 60}m</span>
        {(["open", "high", "low", "close"] as const).map((k) => (
          <span key={k}>
            {k[0].toUpperCase()}{" "}
            <em>
              {Number(candle[k]).toLocaleString(undefined, {
                maximumFractionDigits: 2,
              })}
            </em>
          </span>
        ))}
        <span>
          {new Date(candle.time * 1000)
            .toISOString()
            .slice(5, 16)
            .replace("T", " ")}{" "}
          UTC
        </span>
      </div>
      <div className="chart-canvas-wrap">
        <div className={`chart-canvas tool-${props.tool}`} ref={root} />
        {frame && (
          <DrawingLayer
            frame={frame}
            drawings={props.drawings}
            draft={activeDraft}
            eraser={props.tool === "eraser"}
            onErase={props.onErase}
          />
        )}
      </div>
      <div className="chart-caption">
        <span>{hint}</span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          TradingView Lightweight Charts™ ↗
        </a>
      </div>
    </div>
  );
}
