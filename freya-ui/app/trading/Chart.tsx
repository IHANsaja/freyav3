"use client";
import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  createSeriesMarkers,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Session, Report } from "./types";
export default function Chart({
  session,
  report,
}: {
  session: Session;
  report: Report | null;
}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!root.current) return;
    const chart = createChart(root.current, {
      autoSize: true,
      height: 430,
      layout: {
        background: { type: ColorType.Solid, color: "#101014" },
        textColor: "#a8a6b1",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "#202026" },
        horzLines: { color: "#202026" },
      },
      timeScale: { timeVisible: true },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#64c7b1",
      downColor: "#e46c7e",
      wickUpColor: "#64c7b1",
      wickDownColor: "#e46c7e",
      borderVisible: false,
    });
    series.setData(
      session.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: +c.open,
        high: +c.high,
        low: +c.low,
        close: +c.close,
      })),
    );
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volume
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    series
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.08, bottom: 0.23 } });
    volume.setData(
      session.candles.map((c) => ({
        time: c.time as UTCTimestamp,
        value: +c.volume,
        color: +c.close >= +c.open ? "#64c7b133" : "#e46c7e33",
      })),
    );
    const ema = chart.addSeries(LineSeries, {
      color: "#e5bf76",
      lineWidth: 1,
      priceLineVisible: false,
    });
    ema.setData(
      session.indicators
        .filter((i) => i.ema !== null)
        .map((i) => ({ time: i.time as UTCTimestamp, value: i.ema! })),
    );
    createSeriesMarkers(
      series,
      session.fills.map((f) => ({
        time: f.time as UTCTimestamp,
        position:
          f.side === "buy" ? ("belowBar" as const) : ("aboveBar" as const),
        color: "#e5bf76",
        shape: f.side === "buy" ? ("arrowUp" as const) : ("arrowDown" as const),
        text: `${f.side} ${f.quantity}`,
      })),
    );
    if (report?.revision === session.revision)
      report.analysis?.zones.forEach((z) =>
        series.createPriceLine({
          price: (+z.low + +z.high) / 2,
          color: "#b09ae5",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `${z.kind} · ${z.evidence.join(", ")}`,
        }),
      );
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [session, report]);
  return (
    <div>
      <div ref={root} style={{ height: 430 }} />
      <a
        className="text-xs text-zinc-400"
        href="https://www.tradingview.com/"
        target="_blank"
        rel="noreferrer"
      >
        Charts powered by TradingView Lightweight Charts™
      </a>
    </div>
  );
}
