/**
 * TradingChart.tsx — TradingView Lightweight Charts v5 wrapper.
 *
 * Overlays (main panel):
 *   - Candlesticks with gold highlight on breakout-volume bars (RVOL ≥ 2×)
 *   - Volume histogram with rolling-average line
 *   - VWAP line + ±1σ / ±2σ bands
 *   - Opening Range high/low as price lines (labeled on axis: "OR Hi" / "OR Lo")
 *   - Swing structure markers: HH / HL / LH / LL from consecutive pivot comparison
 *   - Open position price lines: Entry / Stop / Target / Trail
 *   - Position indicator card (TradingView-style) — toggleable
 *   - Trade entry/exit markers with crosshair tooltip
 *
 * Sub-panels (below main chart, time-scale synced):
 *   - RSI (14) with overbought (70) / oversold (30) dashed lines
 *   - MACD (12/26/9): histogram + MACD line + signal line
 *
 * Chart axis shows 12h AM/PM time (not military).
 */
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  CrosshairMode,
  ColorType,
  LineStyle,
  TickMarkType,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  SeriesMarker,
  Time,
  IPriceLine,
  AutoscaleInfo,
} from "lightweight-charts";
import type { Bar, Trade } from "../../lib/api";
import { useThemeStore } from "../../store/theme";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface PositionLevels {
  entry?: number;
  stop?: number;
  target?: number;
  trail?: number;
  direction?: "long" | "short";   // "long" = call, "short" = put
  contracts?: number;              // number of contracts
}

interface Props {
  bars: Bar[];
  trades?: Trade[];
  showVwap?: boolean;
  showVwapBands?: boolean;
  showOR?: boolean;
  showSwings?: boolean;
  showPositionCard?: boolean;   // toggle the TradingView-style position overlay card
  showRsi?: boolean;            // toggle RSI sub-panel (default: true)
  showMacd?: boolean;           // toggle MACD sub-panel (default: true)
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  height?: number;
  ticker?: string;
}

// ─── Color palette ────────────────────────────────────────────────────────────

function colors(dark: boolean) {
  return {
    background:   dark ? "#0d1117" : "#ffffff",
    text:         dark ? "#8b949e" : "#5a6476",
    grid:         dark ? "#21262d" : "#f0f2f7",
    border:       dark ? "#30363d" : "#e2e5ed",
    up:           dark ? "#3fb950" : "#16a34a",
    down:         dark ? "#f85149" : "#dc2626",
    vwap:         dark ? "#58a6ff" : "#2563eb",
    vwapBand1:    dark ? "#58a6ffcc" : "#2563eb99",   // ±1σ — solid, visible
    vwapBand2:    dark ? "#58a6ff66" : "#2563eb55",   // ±2σ — lighter
    orHigh:       dark ? "#4ade80" : "#16a34a",       // bright green
    orLow:        dark ? "#f87171" : "#dc2626",       // bright red
    volAvg:       dark ? "#9ca3af" : "#6b7280",
    breakout:     "#f59e0b",                           // gold
    entry:        "#eab308",                           // yellow
    stop:         "#dc2626",                           // red
    target:       "#16a34a",                           // green
    trail:        "#9333ea",                           // purple
    buyMarker:    "#38bdf8",                           // sky blue
    sellMarker:   "#e879f9",                           // pink/purple
    swingHH:      dark ? "#ff6b6b" : "#cc0000",       // HH/LH — bright red
    swingHL:      dark ? "#4ade80" : "#15803d",       // HL/LL — bright green
    // RSI
    rsi:          dark ? "#a78bfa" : "#7c3aed",       // violet
    rsiOB:        dark ? "#f87171" : "#dc2626",       // overbought line at 70
    rsiOS:        dark ? "#4ade80" : "#16a34a",       // oversold line at 30
    rsiMid:       dark ? "#374151" : "#d1d5db",       // midline at 50 — subtle
    // MACD
    macdLine:     dark ? "#f59e0b" : "#d97706",       // gold
    macdSignal:   dark ? "#e879f9" : "#9333ea",       // purple
    macdHistPos:  dark ? "#3fb950" : "#16a34a",       // green histogram bars
    macdHistNeg:  dark ? "#f85149" : "#dc2626",       // red histogram bars
  };
}

// ─── Swing detection: HH / HL / LH / LL classification ───────────────────────

interface SwingPoint {
  idx: number;
  time: Time;
  price: number;
  kind: "SH" | "SL";
  label: string;   // HH | LH | HL | LL (or SH/SL for first occurrence)
}

function detectSwings(bars: Bar[], lookback = 3): SwingPoint[] {
  const rawHighs: { idx: number; time: Time; price: number }[] = [];
  const rawLows:  { idx: number; time: Time; price: number }[] = [];

  for (let i = lookback; i < bars.length - lookback; i++) {
    const b = bars[i];
    let isHigh = true, isLow = true;
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue;
      if (bars[j].high >= b.high) isHigh = false;
      if (bars[j].low  <= b.low)  isLow  = false;
    }
    if (isHigh) rawHighs.push({ idx: i, time: toTime(b.time), price: b.high });
    if (isLow)  rawLows.push( { idx: i, time: toTime(b.time), price: b.low  });
  }

  const out: SwingPoint[] = [];

  // Classify consecutive pivot highs: HH (higher high) or LH (lower high)
  let prevHighPrice: number | null = null;
  for (const h of rawHighs) {
    let label: string;
    if (prevHighPrice === null)       label = "SH";
    else if (h.price > prevHighPrice) label = "HH";
    else                              label = "LH";
    prevHighPrice = h.price;
    out.push({ ...h, kind: "SH", label });
  }

  // Classify consecutive pivot lows: HL (higher low) or LL (lower low)
  let prevLowPrice: number | null = null;
  for (const l of rawLows) {
    let label: string;
    if (prevLowPrice === null)       label = "SL";
    else if (l.price > prevLowPrice) label = "HL";
    else                             label = "LL";
    prevLowPrice = l.price;
    out.push({ ...l, kind: "SL", label });
  }

  out.sort((a, b) => a.idx - b.idx);
  return out;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toTime(iso: string): Time {
  return (new Date(iso).getTime() / 1000) as Time;
}

function rollingMean(arr: number[], n: number): (number | null)[] {
  return arr.map((_, i) => {
    if (i < n - 1) return null;
    return arr.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n;
  });
}

// ─── Technical indicators (computed client-side from bar closes) ──────────────

/**
 * Exponential Moving Average.
 * Seeds with a simple average of the first `period` bars,
 * then applies the EMA multiplier for subsequent bars.
 * Returns null until there is enough data.
 */
function calcEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  if (data.length < period) return result;
  const k = 2 / (period + 1);
  // Seed: simple average of first `period` values
  let ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;
  result[period - 1] = ema;
  for (let i = period; i < data.length; i++) {
    ema = data[i] * k + ema * (1 - k);
    result[i] = ema;
  }
  return result;
}

/**
 * RSI using Wilder smoothing (standard).
 * Returns null for the first `period` bars.
 */
function calcRSI(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return result;

  // Seed: simple average of first `period` gains and losses
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) avgGain += d;
    else        avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  // Wilder smoothing for subsequent bars
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    const gain = d > 0 ? d : 0;
    const loss = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return result;
}

interface MACDData {
  macd:   (number | null)[];
  signal: (number | null)[];
  hist:   (number | null)[];
}

/**
 * MACD = EMA(fast) − EMA(slow), Signal = EMA(sig) of MACD.
 * Standard parameters: fast=12, slow=26, sig=9.
 */
function calcMACD(closes: number[], fast = 12, slow = 26, sig = 9): MACDData {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);

  // MACD line = fast − slow (null until both EMAs are available)
  const macdLine: (number | null)[] = closes.map((_, i) => {
    const f = emaFast[i], s = emaSlow[i];
    return f != null && s != null ? f - s : null;
  });

  const signalLine: (number | null)[] = new Array(closes.length).fill(null);
  const histLine:   (number | null)[] = new Array(closes.length).fill(null);

  // Signal EMA seeds from the first `sig` MACD values
  const firstIdx = macdLine.findIndex(v => v != null);
  if (firstIdx === -1 || firstIdx + sig > closes.length) {
    return { macd: macdLine, signal: signalLine, hist: histLine };
  }

  const seedSlice = macdLine.slice(firstIdx, firstIdx + sig) as number[];
  const sigK = 2 / (sig + 1);
  let sigEma = seedSlice.reduce((a, b) => a + b, 0) / sig;
  const seedEnd = firstIdx + sig - 1;
  signalLine[seedEnd] = sigEma;
  histLine[seedEnd]   = (macdLine[seedEnd] ?? 0) - sigEma;

  for (let i = seedEnd + 1; i < closes.length; i++) {
    const m = macdLine[i];
    if (m == null) continue;
    sigEma = m * sigK + sigEma * (1 - sigK);
    signalLine[i] = sigEma;
    histLine[i]   = m - sigEma;
  }

  return { macd: macdLine, signal: signalLine, hist: histLine };
}

// ─── Component ───────────────────────────────────────────────────────────────

export function TradingChart({
  bars,
  trades = [],
  showVwap = true,
  showVwapBands = true,
  showOR = true,
  showSwings = true,
  showPositionCard = true,
  showRsi = true,
  showMacd = true,
  orHigh,
  orLow,
  positionLevels,
  height = 420,
  ticker,
}: Props) {
  // ── DOM container refs ───────────────────────────────────────────────────
  const containerRef     = useRef<HTMLDivElement>(null);
  const rsiContainerRef  = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);

  // ── Chart instance refs ─────────────────────────────────────────────────
  const chartRef     = useRef<IChartApi | null>(null);
  const rsiChartRef  = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  // ── Main chart series refs ───────────────────────────────────────────────
  const candleRef    = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef       = useRef<ISeriesApi<"Histogram"> | null>(null);
  const volAvgRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapRef      = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapU1Ref    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapL1Ref    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapU2Ref    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapL2Ref    = useRef<ISeriesApi<"Line"> | null>(null);

  // ── RSI / MACD series refs ───────────────────────────────────────────────
  const rsiSeriesRef   = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef    = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdLineRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef  = useRef<ISeriesApi<"Line"> | null>(null);

  // ── Price-line refs ──────────────────────────────────────────────────────
  const priceLineRefs    = useRef<IPriceLine[]>([]);
  const orPriceLineRefs  = useRef<IPriceLine[]>([]);

  // Mutable ref so the autoscaleInfoProvider closure always reads current OR values
  const orRef = useRef<{ high: number | null; low: number | null }>({ high: null, low: null });

  // Tooltip div ref
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const { theme } = useThemeStore();
  const dark = theme === "dark";
  const C = colors(dark);

  // ── Build charts on mount / theme / panel-visibility change ─────────────
  useEffect(() => {
    if (!containerRef.current) return;

    // Shared time-axis formatter: 12-hour AM/PM
    const tickMarkFormatter = (time: Time, tickMarkType: TickMarkType) => {
      const epochSec = time as number;
      const d = new Date(epochSec * 1000);
      if (tickMarkType === TickMarkType.Time) {
        let h = d.getHours();
        const m = String(d.getMinutes()).padStart(2, "0");
        const ampm = h >= 12 ? "PM" : "AM";
        h = h % 12 || 12;
        return `${h}:${m} ${ampm}`;
      }
      return `${d.getMonth() + 1}/${d.getDate()}`;
    };

    // Shared layout/grid options used by all three chart instances
    const baseLayout = {
      layout: {
        background: { type: ColorType.Solid, color: C.background },
        textColor: C.text,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: C.grid },
        horzLines: { color: C.grid },
      },
      crosshair:       { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: C.border, autoScale: true },
    };

    // ── Main price chart ──────────────────────────────────────────────────
    const chart = createChart(containerRef.current, {
      ...baseLayout,
      width:  containerRef.current.clientWidth,
      height,
      // Explicit scroll/zoom so wheel events work inside a scrollable parent
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale:  { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      timeScale: {
        borderColor:    C.border,
        timeVisible:    true,
        secondsVisible: false,
        tickMarkFormatter,
      },
    });
    chartRef.current = chart;

    // Candles — autoscale provider that pulls OR Hi/Lo into view when nearby
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor:         C.up,
      downColor:       C.down,
      borderUpColor:   C.up,
      borderDownColor: C.down,
      wickUpColor:     C.up,
      wickDownColor:   C.down,
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const base = original();
        const { high: orHi, low: orLo } = orRef.current;
        if (!base?.priceRange || (orHi == null && orLo == null)) return base;
        const naturalRange = base.priceRange.maxValue - base.priceRange.minValue;
        const margin = naturalRange * 2;
        const minVal = (orLo != null && orLo >= base.priceRange.minValue - margin)
          ? Math.min(base.priceRange.minValue, orLo) : base.priceRange.minValue;
        const maxVal = (orHi != null && orHi <= base.priceRange.maxValue + margin)
          ? Math.max(base.priceRange.maxValue, orHi) : base.priceRange.maxValue;
        return { priceRange: { minValue: minVal, maxValue: maxVal }, margins: base.margins };
      },
    }) as unknown as ISeriesApi<"Candlestick">;

    // Volume histogram (separate price scale, bottom 15% of chart height)
    volRef.current = chart.addSeries(HistogramSeries, {
      color: C.grid,
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    }) as unknown as ISeriesApi<"Histogram">;
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    volAvgRef.current = chart.addSeries(LineSeries, {
      color: C.volAvg, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceFormat: { type: "volume" }, priceScaleId: "vol",
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // VWAP + bands
    vwapRef.current = chart.addSeries(LineSeries, {
      color: C.vwap, lineWidth: 2,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    vwapU2Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand2, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;
    vwapL2Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand2, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;
    vwapU1Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand1, lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;
    vwapL1Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand1, lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── RSI sub-chart (100px tall, read-only — synced from main) ─────────
    if (showRsi && rsiContainerRef.current) {
      const rsiChart = createChart(rsiContainerRef.current, {
        ...baseLayout,
        width:  containerRef.current.clientWidth,
        height: 100,
        // Disable user pan/zoom — the main chart drives the viewport for all panels
        handleScroll: false,
        handleScale:  false,
        timeScale: {
          borderColor:    C.border,
          timeVisible:    false,   // no axis labels in the middle panel
          secondsVisible: false,
          tickMarkFormatter,
        },
      });
      rsiChartRef.current = rsiChart;

      rsiSeriesRef.current = rsiChart.addSeries(LineSeries, {
        color:  C.rsi,
        lineWidth: 2,
        priceLineVisible:       false,
        crosshairMarkerVisible: true,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      }) as unknown as ISeriesApi<"Line">;

      // Reference lines: overbought (70), oversold (30), midline (50)
      rsiSeriesRef.current.createPriceLine({
        price: 70, color: C.rsiOB, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, title: "70",
      });
      rsiSeriesRef.current.createPriceLine({
        price: 30, color: C.rsiOS, lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, title: "30",
      });
      rsiSeriesRef.current.createPriceLine({
        price: 50, color: C.rsiMid, lineWidth: 1, lineStyle: LineStyle.Dotted,
        axisLabelVisible: false, title: "",
      });
    }

    // ── MACD sub-chart (120px tall, read-only — synced from main) ────────
    if (showMacd && macdContainerRef.current) {
      const macdChart = createChart(macdContainerRef.current, {
        ...baseLayout,
        width:  containerRef.current.clientWidth,
        height: 120,
        handleScroll: false,
        handleScale:  false,
        timeScale: {
          borderColor:    C.border,
          timeVisible:    true,    // bottom-most panel — show the time axis
          secondsVisible: false,
          tickMarkFormatter,
        },
      });
      macdChartRef.current = macdChart;

      // Histogram: green bars above zero, red below
      macdHistRef.current = macdChart.addSeries(HistogramSeries, {
        priceLineVisible: false,
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
      }) as unknown as ISeriesApi<"Histogram">;

      // Zero line anchored on the histogram series
      macdHistRef.current.createPriceLine({
        price: 0, color: C.border, lineWidth: 1, lineStyle: LineStyle.Solid,
        axisLabelVisible: false, title: "",
      });

      // MACD line (gold)
      macdLineRef.current = macdChart.addSeries(LineSeries, {
        color: C.macdLine, lineWidth: 2,
        priceLineVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
      }) as unknown as ISeriesApi<"Line">;

      // Signal line (purple)
      macdSignalRef.current = macdChart.addSeries(LineSeries, {
        color: C.macdSignal, lineWidth: 1,
        priceLineVisible: false, crosshairMarkerVisible: false,
        priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
      }) as unknown as ISeriesApi<"Line">;
    }

    // ── Time-scale sync: main chart → sub-panels ──────────────────────────
    // One-directional because sub-panels have handleScroll/Scale disabled.
    const syncHandler = (range: { from: number; to: number } | null) => {
      if (!range) return;
      rsiChartRef.current?.timeScale().setVisibleLogicalRange(range);
      macdChartRef.current?.timeScale().setVisibleLogicalRange(range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncHandler);

    // ── Resize observer: keep all panels the same width ───────────────────
    const ro = new ResizeObserver(() => {
      if (!containerRef.current) return;
      const w = containerRef.current.clientWidth;
      chart.applyOptions({ width: w });
      rsiChartRef.current?.applyOptions({ width: w });
      macdChartRef.current?.applyOptions({ width: w });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncHandler);
      chart.remove();
      chartRef.current    = null;
      candleRef.current   = null;
      volRef.current      = null;
      volAvgRef.current   = null;
      vwapRef.current     = null;
      vwapU1Ref.current   = null;
      vwapL1Ref.current   = null;
      vwapU2Ref.current   = null;
      vwapL2Ref.current   = null;
      priceLineRefs.current   = [];
      orPriceLineRefs.current = [];

      rsiChartRef.current?.remove();
      rsiChartRef.current  = null;
      rsiSeriesRef.current = null;

      macdChartRef.current?.remove();
      macdChartRef.current  = null;
      macdHistRef.current   = null;
      macdLineRef.current   = null;
      macdSignalRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, dark, showRsi, showMacd]);

  // ── Feed data & overlays whenever bars / props change ────────────────────
  useEffect(() => {
    if (!candleRef.current || !bars.length) return;

    const breakoutThreshold = 2.0;
    const closes = bars.map(b => b.close);

    // ── Candles ──────────────────────────────────────────────────────────────
    candleRef.current.setData(
      bars.map((b) => {
        const isBreakout = (b.rvol ?? 0) >= breakoutThreshold;
        return {
          time:             toTime(b.time),
          open:  b.open, high: b.high, low: b.low, close: b.close,
          borderUpColor:   isBreakout ? C.breakout : C.up,
          borderDownColor: isBreakout ? C.breakout : C.down,
          wickUpColor:     isBreakout ? C.breakout : C.up,
          wickDownColor:   isBreakout ? C.breakout : C.down,
        };
      })
    );

    // ── Volume + rolling average ─────────────────────────────────────────────
    const vols = bars.map((b) => b.volume);
    const avgWindow = Math.min(20, bars.length);
    const avgVol = rollingMean(vols, avgWindow);

    volRef.current?.setData(
      bars.map((b) => {
        const isBreakout = (b.rvol ?? 0) >= breakoutThreshold;
        const base = b.close >= b.open ? C.up : C.down;
        return { time: toTime(b.time), value: b.volume, color: isBreakout ? C.breakout + "bb" : base + "55" };
      })
    );
    volAvgRef.current?.setData(
      bars
        .map((b, i) => avgVol[i] != null ? { time: toTime(b.time), value: avgVol[i]! } : null)
        .filter(Boolean) as { time: Time; value: number }[]
    );

    // ── VWAP line ────────────────────────────────────────────────────────────
    vwapRef.current?.setData(
      showVwap
        ? bars.filter((b) => b.vwap != null).map((b) => ({ time: toTime(b.time), value: b.vwap! }))
        : []
    );

    // ── VWAP bands ───────────────────────────────────────────────────────────
    if (showVwap && showVwapBands) {
      vwapU1Ref.current?.setData(bars.filter((b) => b.vwap_upper1 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_upper1! })));
      vwapL1Ref.current?.setData(bars.filter((b) => b.vwap_lower1 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_lower1! })));
      vwapU2Ref.current?.setData(bars.filter((b) => b.vwap_upper2 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_upper2! })));
      vwapL2Ref.current?.setData(bars.filter((b) => b.vwap_lower2 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_lower2! })));
    } else {
      vwapU1Ref.current?.setData([]);
      vwapL1Ref.current?.setData([]);
      vwapU2Ref.current?.setData([]);
      vwapL2Ref.current?.setData([]);
    }

    // ── Opening Range price lines ─────────────────────────────────────────────
    // Update mutable ref so autoscaleInfoProvider closure sees current values
    orRef.current = { high: orHigh ?? null, low: orLow ?? null };

    for (const pl of orPriceLineRefs.current) {
      try { candleRef.current?.removePriceLine(pl); } catch (_) { /* already gone */ }
    }
    orPriceLineRefs.current = [];

    if (showOR && candleRef.current) {
      if (orHigh != null) {
        const pl = candleRef.current.createPriceLine({
          price: orHigh, color: C.orHigh, lineWidth: 2, lineStyle: LineStyle.Solid,
          axisLabelVisible: true, title: "OR Hi",
        });
        orPriceLineRefs.current.push(pl);
      }
      if (orLow != null) {
        const pl = candleRef.current.createPriceLine({
          price: orLow, color: C.orLow, lineWidth: 2, lineStyle: LineStyle.Solid,
          axisLabelVisible: true, title: "OR Lo",
        });
        orPriceLineRefs.current.push(pl);
      }
    }

    // ── Swing structure + trade markers ──────────────────────────────────────
    const tradeMarkers: SeriesMarker<Time>[] = [];

    for (const t of trades) {
      if (t.entry_time) tradeMarkers.push({
        time: toTime(t.entry_time), position: "belowBar",
        color: C.buyMarker, shape: "arrowUp",
        text: `BUY ${t.ticker}`, size: 1,
      });
      if (t.exit_time) tradeMarkers.push({
        time: toTime(t.exit_time), position: "aboveBar",
        color: C.sellMarker, shape: "arrowDown",
        text: `SELL ${t.exit_reason ?? ""}`, size: 1,
      });
    }

    if (showSwings) {
      const swings = detectSwings(bars, 3);
      for (const sw of swings) {
        const isHigh = sw.kind === "SH";
        let color: string;
        if (sw.label === "HH" || sw.label === "HL")      color = C.swingHL;
        else if (sw.label === "LH" || sw.label === "LL") color = C.swingHH;
        else                                              color = isHigh ? C.swingHH : C.swingHL;
        tradeMarkers.push({
          time:     sw.time,
          position: isHigh ? "aboveBar" : "belowBar",
          color,
          shape:    isHigh ? "arrowDown" : "arrowUp",
          text:     sw.label,
          size:     1,
        });
      }
    }

    tradeMarkers.sort((a, b) => (a.time as number) - (b.time as number));
    createSeriesMarkers(candleRef.current, tradeMarkers);

    // ── Position price lines (entry / stop / target / trail) ─────────────────
    if (candleRef.current) {
      for (const pl of priceLineRefs.current) {
        try { candleRef.current.removePriceLine(pl); } catch (_) { /* already removed */ }
      }
      priceLineRefs.current = [];

      if (positionLevels) {
        type PriceKey = "entry" | "stop" | "target" | "trail";
        const defs: { key: PriceKey; color: string; label: string; dash: boolean }[] = [
          { key: "entry",  color: C.entry,  label: "Entry",  dash: false },
          { key: "stop",   color: C.stop,   label: "Stop",   dash: false },
          { key: "target", color: C.target, label: "Target", dash: false },
          { key: "trail",  color: C.trail,  label: "Trail",  dash: true  },
        ];
        for (const def of defs) {
          const price = positionLevels[def.key] as number | undefined;
          if (price != null && price > 0) {
            const pl = candleRef.current.createPriceLine({
              price,
              color: def.color,
              lineWidth: 1,
              lineStyle: def.dash ? LineStyle.Dashed : LineStyle.Solid,
              axisLabelVisible: true,
              title: def.label,
            });
            priceLineRefs.current.push(pl);
          }
        }
      }
    }

    chartRef.current?.timeScale().fitContent();

    // ── RSI data ──────────────────────────────────────────────────────────────
    if (showRsi && rsiSeriesRef.current) {
      const rsiValues = calcRSI(closes, 14);
      rsiSeriesRef.current.setData(
        bars
          .map((b, i) => rsiValues[i] != null ? { time: toTime(b.time), value: rsiValues[i]! } : null)
          .filter(Boolean) as { time: Time; value: number }[]
      );
      // Mirror the main chart's current viewport into the RSI panel
      rsiChartRef.current?.timeScale().fitContent();
    }

    // ── MACD data ─────────────────────────────────────────────────────────────
    if (showMacd && macdHistRef.current && macdLineRef.current && macdSignalRef.current) {
      const { macd, signal, hist } = calcMACD(closes);

      // Histogram: semi-transparent green above zero, red below
      macdHistRef.current.setData(
        bars
          .map((b, i) => hist[i] != null
            ? { time: toTime(b.time), value: hist[i]!, color: hist[i]! >= 0 ? C.macdHistPos + "bb" : C.macdHistNeg + "bb" }
            : null)
          .filter(Boolean) as { time: Time; value: number; color: string }[]
      );
      macdLineRef.current.setData(
        bars
          .map((b, i) => macd[i] != null ? { time: toTime(b.time), value: macd[i]! } : null)
          .filter(Boolean) as { time: Time; value: number }[]
      );
      macdSignalRef.current.setData(
        bars
          .map((b, i) => signal[i] != null ? { time: toTime(b.time), value: signal[i]! } : null)
          .filter(Boolean) as { time: Time; value: number }[]
      );
      macdChartRef.current?.timeScale().fitContent();
    }

  }, [bars, trades, showVwap, showVwapBands, showOR, showSwings, orHigh, orLow, positionLevels, showRsi, showMacd]);
  // NOTE: C (color object) intentionally not in deps — color changes trigger a full
  // chart recreation via the `dark` dep in the chart-creation effect above.

  // ── Crosshair tooltip for trade markers ──────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle || !trades.length) return;

    const lookup = new Map<number, string>();
    for (const t of trades) {
      if (t.entry_time) {
        const ts = Math.round(new Date(t.entry_time).getTime() / 1000);
        lookup.set(ts, `BUY ${t.ticker} @ ${t.entry_price?.toFixed(2) ?? "—"}`);
      }
      if (t.exit_time) {
        const ts = Math.round(new Date(t.exit_time).getTime() / 1000);
        lookup.set(ts, `SELL ${t.exit_reason ?? ""} @ ${t.exit_price?.toFixed(2) ?? "—"}`);
      }
    }

    const handleCrosshair = (param: { time?: Time }) => {
      const tt = tooltipRef.current;
      if (!tt) return;
      if (!param.time) { tt.style.display = "none"; return; }
      const label = lookup.get(param.time as number);
      if (!label) { tt.style.display = "none"; return; }
      tt.textContent = label;
      tt.style.display = "block";
    };

    chart.subscribeCrosshairMove(handleCrosshair);
    return () => chart.unsubscribeCrosshairMove(handleCrosshair);
  }, [trades]);

  // ── Position overlay card ─────────────────────────────────────────────────
  // Direction badge always visible; STP/ENT/TGT detail rows appear on hover.
  const [cardHovered, setCardHovered] = useState(false);

  const posCard = (() => {
    const pl = positionLevels;
    if (!pl?.entry) return null;

    const isLong   = (pl.direction ?? "long") === "long";
    const stopPct  = pl.stop   ? Math.abs((pl.entry - pl.stop)   / pl.entry * 100) : null;
    const tgtPct   = pl.target ? Math.abs((pl.target - pl.entry) / pl.entry * 100) : null;
    const rr       = (stopPct && tgtPct && stopPct > 0) ? (tgtPct / stopPct) : null;
    const riskDol  = (pl.stop && pl.contracts)
      ? Math.abs((pl.entry - pl.stop) * pl.contracts * 100) : null;
    const rewDol   = (pl.target && pl.contracts)
      ? Math.abs((pl.target - pl.entry) * pl.contracts * 100) : null;
    const fmt    = (n: number) => n.toFixed(2);
    const fmtPct = (n: number | null) => n != null ? `${n.toFixed(1)}%` : "—";

    return (
      <div
        onMouseEnter={() => setCardHovered(true)}
        onMouseLeave={() => setCardHovered(false)}
        style={{
          position: "absolute", top: 36, left: 8, zIndex: 20,
          pointerEvents: "auto",
          fontFamily: "JetBrains Mono, monospace", fontSize: 11,
          display: "flex", flexDirection: "column", gap: 2,
          minWidth: 180, cursor: "default",
        }}
      >
        {/* Direction badge — always visible */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          background: isLong ? "rgba(63,185,80,0.18)" : "rgba(248,81,73,0.18)",
          border: `1px solid ${isLong ? C.target : C.stop}`,
          borderRadius: 4, padding: "3px 8px",
          color: isLong ? C.target : C.stop,
          fontWeight: 700, fontSize: 10, letterSpacing: "0.08em",
          width: "fit-content",
        }}>
          {isLong ? "▲ LONG" : "▼ SHORT"}
          {pl.contracts ? ` · ${pl.contracts}×` : ""}
          <span style={{ opacity: 0.6, fontWeight: 400, fontSize: 9 }}>
            {cardHovered ? " ▲" : " ▼"}
          </span>
        </div>

        {/* Detail rows — only on hover */}
        {cardHovered && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {pl.stop && (
              <div style={{ background: "rgba(248,81,73,0.12)", border: "1px solid rgba(248,81,73,0.40)", borderRadius: 3, padding: "3px 8px" }}>
                <span style={{ color: C.stop, fontWeight: 600 }}>STP</span>
                <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.stop)} ({fmtPct(stopPct)})</span>
                {riskDol != null && <span style={{ color: C.stop }}> · -${fmt(riskDol)}</span>}
              </div>
            )}
            <div style={{ background: "rgba(234,179,8,0.10)", border: "1px solid rgba(234,179,8,0.35)", borderRadius: 3, padding: "3px 8px" }}>
              <span style={{ color: C.entry, fontWeight: 600 }}>ENT</span>
              <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.entry)}</span>
              {rr != null && <span style={{ color: "var(--ink-muted)" }}> · R:R {rr.toFixed(2)}</span>}
            </div>
            {pl.target && (
              <div style={{ background: "rgba(63,185,80,0.10)", border: "1px solid rgba(63,185,80,0.35)", borderRadius: 3, padding: "3px 8px" }}>
                <span style={{ color: C.target, fontWeight: 600 }}>TGT</span>
                <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.target)} ({fmtPct(tgtPct)})</span>
                {rewDol != null && <span style={{ color: C.target }}> · +${fmt(rewDol)}</span>}
              </div>
            )}
            {pl.trail && (
              <div style={{ background: "rgba(147,51,234,0.10)", border: "1px solid rgba(147,51,234,0.35)", borderRadius: 3, padding: "3px 8px" }}>
                <span style={{ color: C.trail, fontWeight: 600 }}>TRL</span>
                <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.trail)}</span>
              </div>
            )}
          </div>
        )}
      </div>
    );
  })();

  // ─────────────────────────────────────────────────────────────────────────
  return (
    // onWheel stopPropagation: prevents the page's overflow-y:auto container
    // from scrolling when the user wheel-zooms the chart.
    <div className="flex flex-col w-full"
      onWheel={(e) => e.stopPropagation()}
    >
      {/* ── Main price chart ─────────────────────────────────────────────── */}
      <div className="relative w-full" style={{ height }}>

        {/* Ticker label */}
        {ticker && (
          <div className="absolute top-2 left-3 z-10 text-xs font-mono font-semibold"
               style={{ color: "var(--ink-muted)" }}>
            {ticker}
          </div>
        )}

        {/* Overlay legend + Fit button */}
        <div className="absolute top-2 right-3 z-10 flex items-center gap-2 text-[10px] font-mono select-none"
             style={{ color: "var(--ink-muted)" }}>
          <button
            title="Fit chart to data (reset zoom & center)"
            onClick={() => {
              if (!chartRef.current) return;
              chartRef.current.timeScale().fitContent();
              chartRef.current.priceScale("right").applyOptions({ autoScale: true });
            }}
            style={{
              background: "transparent",
              border: `1px solid var(--border)`,
              borderRadius: 3, padding: "1px 5px",
              cursor: "pointer", color: "var(--ink-muted)",
              fontSize: 11, lineHeight: 1.4,
            }}
          >
            ⊡
          </button>
          <span className="pointer-events-none">
            {showVwap && <span style={{ color: C.vwap }}>VWAP </span>}
            {showVwap && showVwapBands && <span style={{ color: C.vwapBand1 }}>±1σ </span>}
            {showVwap && showVwapBands && <span style={{ color: C.vwapBand2 }}>±2σ </span>}
            {showOR   && orHigh != null && <span style={{ color: C.orHigh }}>OR Hi </span>}
            {showOR   && orLow  != null && <span style={{ color: C.orLow  }}>OR Lo</span>}
          </span>
        </div>

        {/* Position indicator card */}
        {showPositionCard && posCard}

        {/* Main chart canvas */}
        <div ref={containerRef} className="w-full h-full" />

        {/* Crosshair trade tooltip */}
        <div
          ref={tooltipRef}
          style={{
            display: "none", position: "absolute",
            bottom: 40, left: 60,
            background: dark ? "#1c2128" : "#f6f8fa",
            border: `1px solid ${C.border}`,
            borderRadius: 4, padding: "4px 8px",
            fontSize: 11, fontFamily: "JetBrains Mono, monospace",
            color: C.text, pointerEvents: "none", zIndex: 20,
          }}
        />
      </div>

      {/* ── RSI sub-panel ────────────────────────────────────────────────── */}
      {showRsi && (
        <div className="relative w-full" style={{ height: 100, borderTop: `1px solid ${C.border}` }}>
          {/* Panel label */}
          <div
            className="absolute top-1 left-3 z-10 text-[10px] font-mono select-none pointer-events-none"
            style={{ color: C.rsi }}
          >
            RSI(14)
          </div>
          <div ref={rsiContainerRef} className="w-full h-full" />
        </div>
      )}

      {/* ── MACD sub-panel ───────────────────────────────────────────────── */}
      {showMacd && (
        <div className="relative w-full" style={{ height: 120, borderTop: `1px solid ${C.border}` }}>
          {/* Panel labels */}
          <div className="absolute top-1 left-3 z-10 flex items-center gap-3 text-[10px] font-mono select-none pointer-events-none">
            <span style={{ color: C.macdLine }}>MACD(12,26,9)</span>
            <span style={{ color: C.macdSignal }}>Signal</span>
          </div>
          <div ref={macdContainerRef} className="w-full h-full" />
        </div>
      )}
    </div>
  );
}
