/**
 * chartCore.ts — the chart engine itself: creates the main candle/volume
 * chart plus RSI/MACD sub-charts, and feeds them data.
 *
 * This is deliberately built on lightweight-charts ONLY (klinecharts is
 * being retired). Reason: every "candles won't pan/zoom/switch timeframe"
 * report traced back to the klinecharts side; the lightweight-charts side
 * (the old TradingChart.tsx) never had that class of bug in its entire
 * multi-year commit history. Native pan/zoom/scale here is handled entirely
 * by the library — this file does not add any custom wheel/zoom/resize
 * workarounds on top of it.
 */
import { useEffect, useRef } from "react";
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries,
  CrosshairMode, ColorType, LineStyle, TickMarkType,
} from "lightweight-charts";
import type { IChartApi, ISeriesApi, Time, TickMarkType as TTickMarkType } from "lightweight-charts";
import type { Bar } from "../../lib/api";
import type { ChartPalette } from "./palette";
import { calcRSI, calcMACD } from "./indicators";

export function toEpochTime(iso: string): Time {
  return (new Date(iso).getTime() / 1000) as Time;
}

export interface ChartCoreRefs {
  chart: IChartApi | null;
  candle: ISeriesApi<"Candlestick"> | null;
  volume: ISeriesApi<"Histogram"> | null;
  rsiChart: IChartApi | null;
  rsiLine: ISeriesApi<"Line"> | null;
  macdChart: IChartApi | null;
  macdHist: ISeriesApi<"Histogram"> | null;
  macdLine: ISeriesApi<"Line"> | null;
  macdSignal: ISeriesApi<"Line"> | null;
}

function tickFormatter(time: Time, type: TTickMarkType) {
  const d = new Date((time as number) * 1000);
  if (type === TickMarkType.Time) {
    let h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, "0");
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${h}:${m} ${ampm}`;
  }
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function useChartCore(
  mainEl: React.RefObject<HTMLDivElement | null>,
  rsiEl: React.RefObject<HTMLDivElement | null>,
  macdEl: React.RefObject<HTMLDivElement | null>,
  palette: ChartPalette,
  opts: { height: number; showRsi: boolean; showMacd: boolean; viewportKey?: string },
) {
  const refs = useRef<ChartCoreRefs>({
    chart: null, candle: null, volume: null,
    rsiChart: null, rsiLine: null,
    macdChart: null, macdHist: null, macdLine: null, macdSignal: null,
  });
  // Polling in a new bar must not reset the user's zoom or recalculate the
  // viewport around every annotation. Refit only when the visible chart
  // context (ticker/timeframe/replay window) actually changes.
  const lastFittedViewportKey = useRef<string | null>(null);

  // ── Create / destroy on mount, theme change, or sub-panel toggle ─────────
  useEffect(() => {
    if (!mainEl.current) return;
    const baseLayout = {
      layout: { background: { type: ColorType.Solid, color: palette.background }, textColor: palette.text, fontFamily: "'JetBrains Mono', monospace", fontSize: 11 },
      grid: { vertLines: { color: palette.grid }, horzLines: { color: palette.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: palette.border, autoScale: true },
    };

    const chart = createChart(mainEl.current, {
      ...baseLayout,
      width: mainEl.current.clientWidth,
      height: opts.height,
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false, rightOffset: 12, barSpacing: 7, tickMarkFormatter: tickFormatter },
    });

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: palette.up, downColor: palette.down,
      borderUpColor: palette.up, borderDownColor: palette.down,
      wickUpColor: palette.up, wickDownColor: palette.down,
    }) as unknown as ISeriesApi<"Candlestick">;

    const volume = chart.addSeries(HistogramSeries, { color: palette.grid, priceFormat: { type: "volume" }, priceScaleId: "vol" }) as unknown as ISeriesApi<"Histogram">;
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    refs.current.chart = chart;
    refs.current.candle = candle;
    refs.current.volume = volume;
    lastFittedViewportKey.current = null;

    let rsiChart: IChartApi | null = null, rsiLine: ISeriesApi<"Line"> | null = null;
    if (opts.showRsi && rsiEl.current) {
      rsiChart = createChart(rsiEl.current, { ...baseLayout, width: mainEl.current.clientWidth, height: 100, handleScroll: false, handleScale: false, timeScale: { borderColor: palette.border, visible: false, tickMarkFormatter: tickFormatter } });
      rsiLine = rsiChart.addSeries(LineSeries, { color: palette.rsi, lineWidth: 2, priceLineVisible: false, priceFormat: { type: "price", precision: 1, minMove: 0.1 } }) as unknown as ISeriesApi<"Line">;
      rsiLine.createPriceLine({ price: 70, color: palette.rsiOB, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "70" });
      rsiLine.createPriceLine({ price: 30, color: palette.rsiOS, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "30" });
      refs.current.rsiChart = rsiChart;
      refs.current.rsiLine = rsiLine;
    }

    let macdChart: IChartApi | null = null;
    if (opts.showMacd && macdEl.current) {
      macdChart = createChart(macdEl.current, { ...baseLayout, width: mainEl.current.clientWidth, height: 120, handleScroll: false, handleScale: false, timeScale: { borderColor: palette.border, timeVisible: true, tickMarkFormatter: tickFormatter } });
      const macdLine = macdChart.addSeries(LineSeries, { color: palette.macdLine, lineWidth: 2, priceScaleId: "right", priceLineVisible: false }) as unknown as ISeriesApi<"Line">;
      const macdSignal = macdChart.addSeries(LineSeries, { color: palette.macdSignal, lineWidth: 2, priceScaleId: "right", priceLineVisible: false }) as unknown as ISeriesApi<"Line">;
      const macdHist = macdChart.addSeries(HistogramSeries, { priceScaleId: "hist", priceLineVisible: false }) as unknown as ISeriesApi<"Histogram">;
      macdChart.priceScale("hist").applyOptions({ scaleMargins: { top: 0.65, bottom: 0 }, visible: false });
      refs.current.macdChart = macdChart;
      refs.current.macdLine = macdLine;
      refs.current.macdSignal = macdSignal;
      refs.current.macdHist = macdHist;
    }

    // Sub-panels follow the main chart's time range — main chart is the only
    // one the user directly pans/zooms (handleScroll/handleScale: false above).
    const syncHandler = (range: { from: Time; to: Time } | null) => {
      if (!range || range.from == null || range.to == null) return;
      try { rsiChart?.timeScale().setVisibleRange(range); } catch { /* not ready */ }
      try { macdChart?.timeScale().setVisibleRange(range); } catch { /* not ready */ }
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(syncHandler);

    let disposed = false;
    const ro = new ResizeObserver(() => {
      // ResizeObserver callbacks already queued by the browser may run after
      // React has started unmounting this chart. Never call into a removed
      // lightweight-charts canvas.
      if (disposed || !mainEl.current) return;
      const w = mainEl.current.clientWidth;
      chart.applyOptions({ width: w });
      rsiChart?.applyOptions({ width: w });
      macdChart?.applyOptions({ width: w });
    });
    ro.observe(mainEl.current);

    return () => {
      disposed = true;
      ro.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(syncHandler);
      chart.remove();
      rsiChart?.remove();
      macdChart?.remove();
      refs.current = { chart: null, candle: null, volume: null, rsiChart: null, rsiLine: null, macdChart: null, macdHist: null, macdLine: null, macdSignal: null };
      lastFittedViewportKey.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [palette.background, opts.height, opts.showRsi, opts.showMacd]);

  // ── Feed data whenever bars change ────────────────────────────────────────
  function setBars(bars: Bar[]) {
    const r = refs.current;
    if (!r.candle) return;
    if (bars.length === 0) {
      r.candle.setData([]);
      r.volume?.setData([]);
      r.rsiLine?.setData([]);
      r.macdLine?.setData([]);
      r.macdSignal?.setData([]);
      r.macdHist?.setData([]);
      return;
    }
    const closes = bars.map((b) => b.close);

    r.candle.setData(bars.map((b) => ({ time: toEpochTime(b.time), open: b.open, high: b.high, low: b.low, close: b.close })));

    r.volume?.setData(bars.map((b) => ({ time: toEpochTime(b.time), value: b.volume, color: b.close >= b.open ? palette.up + "33" : palette.down + "33" })));

    if (r.rsiLine) {
      const rsi = calcRSI(closes, 14);
      r.rsiLine.setData(bars.map((b, i) => (rsi[i] != null ? { time: toEpochTime(b.time), value: rsi[i]! } : null)).filter(Boolean) as { time: Time; value: number }[]);
    }
    if (r.macdLine && r.macdSignal && r.macdHist) {
      const { macd, signal, hist } = calcMACD(closes);
      r.macdLine.setData(bars.map((b, i) => (macd[i] != null ? { time: toEpochTime(b.time), value: macd[i]! } : null)).filter(Boolean) as { time: Time; value: number }[]);
      r.macdSignal.setData(bars.map((b, i) => (signal[i] != null ? { time: toEpochTime(b.time), value: signal[i]! } : null)).filter(Boolean) as { time: Time; value: number }[]);
      r.macdHist.setData(bars.map((b, i) => (hist[i] != null ? { time: toEpochTime(b.time), value: hist[i]!, color: hist[i]! >= 0 ? palette.macdHistPos + "bb" : palette.macdHistNeg + "bb" } : null)).filter(Boolean) as { time: Time; value: number; color: string }[]);
    }

    const viewportKey = opts.viewportKey ?? "default";
    if (lastFittedViewportKey.current !== viewportKey) {
      lastFittedViewportKey.current = viewportKey;
      r.chart?.timeScale().fitContent();
    }
  }

  return { refs, setBars };
}
