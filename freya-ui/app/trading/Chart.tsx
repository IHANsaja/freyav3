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
} from "lightweight-charts";
import type { Session, Report, Candle } from "./types";
export type Drawing = {
  id: string;
  kind: "level" | "trend";
  points: { time: number; price: number }[];
};
export type ChartTool = "cursor" | "level" | "trend";
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
  onSelect: (id: string) => void;
  selected: string | null;
  fit: number;
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
  } | null>(null);
  const [hover, setHover] = useState<Candle | null>(null);
  const [hint, setHint] = useState("");
  const pending = useRef<{ time: number; price: number } | null>(null);
  useEffect(() => {
    latest.current = props;
  }, [props]);
  useEffect(() => {
    pending.current = null;
  }, [props.tool, props.session.id]);
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
    api.current = {
      chart,
      candles,
      close,
      ema,
      volume,
      rsi,
      markers: createSeriesMarkers(candles, []),
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
    const start = (e: PointerEvent) => {
      if (!e.isPrimary || e.button !== 0) {
        down = null;
        return;
      }
      down = { x: e.clientX, y: e.clientY, id: e.pointerId };
      dragged = false;
    };
    const move = (e: PointerEvent) => {
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5)
        dragged = true;
    };
    const finish = (e: PointerEvent) => {
      const anchor = down;
      down = null;
      if (
        !anchor ||
        anchor.id !== e.pointerId ||
        dragged ||
        Math.hypot(e.clientX - anchor.x, e.clientY - anchor.y) > 5
      )
        return;
      const bounds = el.getBoundingClientRect();
      const x = e.clientX - bounds.left,
        y = e.clientY - bounds.top;
      const size = chart.paneSize(0);
      if (x < 0 || y < 0 || x >= size.width || y >= size.height) return;
      const time = chart.timeScale().coordinateToTime(x);
      if (typeof time !== "number") return;
      const p = latest.current;
      const candle = p.session.candles.find((c) => c.time === time);
      if (!candle) return;
      p.onSelect(candle.id);
      if (p.tool === "cursor") return;
      const price = candles.coordinateToPrice(y);
      if (price === null || price <= 0) return;
      const point = { time: Number(time), price: Number(price) };
      if (p.tool === "level")
        p.onDraw({ id: crypto.randomUUID(), kind: "level", points: [point] });
      else if (!pending.current) {
        pending.current = point;
        setHint("Select a second candle to finish the trendline");
      } else if (pending.current.time === point.time)
        setHint("Choose a different candle for the second point");
      else {
        p.onDraw({
          id: crypto.randomUUID(),
          kind: "trend",
          points: [pending.current, point].sort((a, b) => a.time - b.time),
        });
        pending.current = null;
        setHint("");
      }
    };
    const cancel = () => {
      down = null;
    };
    el.addEventListener("pointerdown", start);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", finish);
    el.addEventListener("pointercancel", cancel);
    return () => {
      el.removeEventListener("pointerdown", start);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", finish);
      el.removeEventListener("pointercancel", cancel);
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
    const a = api.current;
    if (!a) return;
    const lines: IPriceLine[] = [];
    const trends: ISeriesApi<"Line">[] = [];
    const times = new Set(props.session.candles.map((c) => c.time));
    props.drawings
      .filter((d) => d.points.every((p) => times.has(p.time)))
      .forEach((d) => {
        if (d.kind === "level")
          lines.push(
            a.candles.createPriceLine({
              price: d.points[0].price,
              color: "#759aff",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: "My level",
            }),
          );
        else {
          const line = a.chart.addSeries(LineSeries, {
            color: "#759aff",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
            autoscaleInfoProvider: () => null,
          });
          line.setData(
            d.points.map((p) => ({
              time: p.time as UTCTimestamp,
              value: p.price,
            })),
          );
          trends.push(line);
        }
      });
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
      trends.forEach((l) => a.chart.removeSeries(l));
    };
  }, [props.drawings, props.report, props.session]);
  const candle =
    hover ??
    props.session.candles.find((c) => c.id === props.selected) ??
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
      <div className="chart-canvas" ref={root} />
      <div className="chart-caption">
        <span>
          {props.tool === "trend" && hint
            ? hint
            : "Click a candle to give Freya its context"}
        </span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          TradingView Lightweight Charts™ ↗
        </a>
      </div>
    </div>
  );
}
