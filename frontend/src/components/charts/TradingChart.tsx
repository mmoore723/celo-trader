/**
 * TradingChart.tsx — TradingView Lightweight Charts v5 wrapper.
 *
 * Overlays:
 *   - Candlesticks with gold highlight on breakout-volume bars (RVOL ≥ 2×)
 *   - Volume histogram with rolling-average line
 *   - VWAP line + ±1σ / ±2σ bands
 *   - Opening Range high/low as price lines (labeled on axis: "OR Hi" / "OR Lo")
 *   - Swing structure markers: HH / HL / LH / LL from consecutive pivot comparison
 *   - Open position price lines: Entry / Stop / Target / Trail
 *   - Position indicator card (TradingView-style) — toggleable
 *   - Trade entry/exit markers with crosshair tooltip
 *
 * Chart axis shows 12h AM/PM time (not military).
 */
import { useEffect, useRef } from "react";
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
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  height?: number;
  ticker?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toTime(iso: string): Time {
  return (new Date(iso).getTime() / 1000) as Time;
}

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
    swingHH:      dark ? "#f85149" : "#dc2626",       // HH/LH — red family
    swingHL:      dark ? "#3fb950" : "#16a34a",       // HL/LL — green family
  };
}

// ─── Swing detection with HH / HL / LH / LL classification ───────────────────

interface SwingPoint {
  idx: number;
  time: Time;
  price: number;
  kind: "SH" | "SL";
  label: string;   // HH | LH | HL | LL (or SH/SL for first occurrence)
}

function detectSwings(bars: Bar[], lookback = 3): SwingPoint[] {
  // 1. Find raw pivots
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

  // 2. Classify consecutive highs: compare each to the one before it
  const out: SwingPoint[] = [];

  let prevHighPrice: number | null = null;
  for (const h of rawHighs) {
    let label: string;
    if (prevHighPrice === null) {
      label = "SH";            // first pivot — no comparison yet
    } else if (h.price > prevHighPrice) {
      label = "HH";            // higher high → bullish structure
    } else {
      label = "LH";            // lower high → bearish pressure
    }
    prevHighPrice = h.price;
    out.push({ ...h, kind: "SH", label });
  }

  let prevLowPrice: number | null = null;
  for (const l of rawLows) {
    let label: string;
    if (prevLowPrice === null) {
      label = "SL";            // first pivot
    } else if (l.price > prevLowPrice) {
      label = "HL";            // higher low → bullish structure
    } else {
      label = "LL";            // lower low → bearish
    }
    prevLowPrice = l.price;
    out.push({ ...l, kind: "SL", label });
  }

  // Sort by bar index so markers are in chronological order
  out.sort((a, b) => a.idx - b.idx);
  return out;
}

// ─── Rolling mean ─────────────────────────────────────────────────────────────
function rollingMean(arr: number[], n: number): (number | null)[] {
  return arr.map((_, i) => {
    if (i < n - 1) return null;
    return arr.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n;
  });
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
  orHigh,
  orLow,
  positionLevels,
  height = 420,
  ticker,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);

  // series refs
  const candleRef    = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef       = useRef<ISeriesApi<"Histogram"> | null>(null);
  const volAvgRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapRef      = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapU1Ref    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapL1Ref    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapU2Ref    = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapL2Ref    = useRef<ISeriesApi<"Line"> | null>(null);

  // price-line refs: position levels (entry/stop/target/trail)
  const priceLineRefs    = useRef<IPriceLine[]>([]);
  // price-line refs: OR hi/lo (replaced from LineSeries → label shows on axis)
  const orPriceLineRefs  = useRef<IPriceLine[]>([]);

  // tooltip div ref
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const { theme } = useThemeStore();
  const dark = theme === "dark";
  const C = colors(dark);

  // ── Build chart on mount / theme change ──────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
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
      crosshair: { mode: CrosshairMode.Normal },
      // Explicitly enable zoom + scroll so they work even inside a
      // scrollable parent (the page's overflow-y:auto .app-main container
      // would otherwise steal wheel events and scroll the page instead).
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale:  { mouseWheel: true, pinch: true, axisPressedMouseMove: { time: true, price: true } },
      rightPriceScale: { borderColor: C.border, autoScale: true },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: false,
        // 12-hour AM/PM axis labels — override the default 24h display
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => {
          const epochSec = time as number;
          const d = new Date(epochSec * 1000);
          if (tickMarkType === TickMarkType.Time) {
            let h = d.getHours();
            const m = String(d.getMinutes()).padStart(2, "0");
            const ampm = h >= 12 ? "PM" : "AM";
            h = h % 12 || 12;
            return `${h}:${m} ${ampm}`;
          }
          // Day / Month / Year marks → show as M/D
          return `${d.getMonth() + 1}/${d.getDate()}`;
        },
      },
    });
    chartRef.current = chart;

    // ── Candles ─────────────────────────────────────────────────────────────
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor:         C.up,
      downColor:       C.down,
      borderUpColor:   C.up,
      borderDownColor: C.down,
      wickUpColor:     C.up,
      wickDownColor:   C.down,
    }) as unknown as ISeriesApi<"Candlestick">;

    // ── Volume histogram ─────────────────────────────────────────────────────
    volRef.current = chart.addSeries(HistogramSeries, {
      color: C.grid,
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    }) as unknown as ISeriesApi<"Histogram">;
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    volAvgRef.current = chart.addSeries(LineSeries, {
      color: C.volAvg, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── VWAP ────────────────────────────────────────────────────────────────
    vwapRef.current = chart.addSeries(LineSeries, {
      color: C.vwap, lineWidth: 2,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── VWAP bands (±2σ outer, ±1σ inner) ───────────────────────────────────
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

    // ── Resize observer ──────────────────────────────────────────────────────
    const ro = new ResizeObserver(() => {
      containerRef.current &&
        chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
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
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, dark]);

  // ── Feed data & overlays on bars / props change ───────────────────────────
  useEffect(() => {
    if (!candleRef.current || !bars.length) return;

    const breakoutThreshold = 2.0;

    // ── Candles ──────────────────────────────────────────────────────────────
    candleRef.current.setData(
      bars.map((b) => {
        const isBreakout = (b.rvol ?? 0) >= breakoutThreshold;
        return {
          time:             toTime(b.time),
          open:             b.open,
          high:             b.high,
          low:              b.low,
          close:            b.close,
          borderUpColor:    isBreakout ? C.breakout : C.up,
          borderDownColor:  isBreakout ? C.breakout : C.down,
          wickUpColor:      isBreakout ? C.breakout : C.up,
          wickDownColor:    isBreakout ? C.breakout : C.down,
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

    // ── Opening Range — now as price lines (gives labeled axis + full-width line)
    // Remove old OR price lines first
    for (const pl of orPriceLineRefs.current) {
      try { candleRef.current?.removePriceLine(pl); } catch (_) { /* already gone */ }
    }
    orPriceLineRefs.current = [];

    if (showOR && candleRef.current) {
      if (orHigh != null) {
        const pl = candleRef.current.createPriceLine({
          price:            orHigh,
          color:            C.orHigh,
          lineWidth:        2,
          lineStyle:        LineStyle.Solid,
          axisLabelVisible: true,
          title:            "OR Hi",
        });
        orPriceLineRefs.current.push(pl);
      }
      if (orLow != null) {
        const pl = candleRef.current.createPriceLine({
          price:            orLow,
          color:            C.orLow,
          lineWidth:        2,
          lineStyle:        LineStyle.Solid,
          axisLabelVisible: true,
          title:            "OR Lo",
        });
        orPriceLineRefs.current.push(pl);
      }
    }

    // ── Swing structure + trade markers ─────────────────────────────────────
    const tradeMarkers: SeriesMarker<Time>[] = [];

    // Trade BUY/SELL markers
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

    // Swing HH / HL / LH / LL markers
    if (showSwings) {
      const swings = detectSwings(bars, 3);
      for (const sw of swings) {
        const isHigh = sw.kind === "SH";
        // Color: HH/HL get their structural color; LH/LL get inverted
        let color: string;
        if (sw.label === "HH" || sw.label === "HL") color = C.swingHL;
        else if (sw.label === "LH" || sw.label === "LL") color = C.swingHH;
        else color = isHigh ? C.swingHH : C.swingHL;   // SH/SL (first)

        tradeMarkers.push({
          time:     sw.time,
          position: isHigh ? "aboveBar" : "belowBar",
          color,
          shape:    isHigh ? "arrowDown" : "arrowUp",
          text:     sw.label,
          size:     0,
        });
      }
    }

    tradeMarkers.sort((a, b) => (a.time as number) - (b.time as number));
    createSeriesMarkers(candleRef.current, tradeMarkers);

    // ── Position price lines (entry/stop/target/trail) ───────────────────────
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
  }, [bars, trades, showVwap, showVwapBands, showOR, showSwings, orHigh, orLow, positionLevels]);

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

    const fmt = (n: number) => n.toFixed(2);
    const fmtPct = (n: number | null) => n != null ? `${n.toFixed(1)}%` : "—";

    return (
      <div
        style={{
          position: "absolute",
          top: 36, left: 8,
          zIndex: 20,
          pointerEvents: "none",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          display: "flex",
          flexDirection: "column",
          gap: 2,
          minWidth: 200,
        }}
      >
        {/* Direction badge */}
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          background: isLong ? "rgba(63,185,80,0.18)" : "rgba(248,81,73,0.18)",
          border: `1px solid ${isLong ? C.target : C.stop}`,
          borderRadius: 4, padding: "2px 8px",
          color: isLong ? C.target : C.stop,
          fontWeight: 700, fontSize: 10, letterSpacing: "0.08em",
        }}>
          {isLong ? "▲ LONG" : "▼ SHORT"}
          {pl.contracts ? ` · ${pl.contracts} contract${pl.contracts > 1 ? "s" : ""}` : ""}
        </div>

        {/* Stop row */}
        {pl.stop && (
          <div style={{ background: "rgba(248,81,73,0.12)", border: "1px solid rgba(248,81,73,0.40)", borderRadius: 3, padding: "3px 8px" }}>
            <span style={{ color: C.stop, fontWeight: 600 }}>STP</span>
            <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.stop)} ({fmtPct(stopPct)})</span>
            {riskDol != null && <span style={{ color: C.stop }}> · -${fmt(riskDol)}</span>}
          </div>
        )}

        {/* Entry row */}
        <div style={{ background: "rgba(234,179,8,0.10)", border: "1px solid rgba(234,179,8,0.35)", borderRadius: 3, padding: "3px 8px" }}>
          <span style={{ color: C.entry, fontWeight: 600 }}>ENT</span>
          <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.entry)}</span>
          {rr != null && <span style={{ color: "var(--ink-muted)" }}> · R:R {rr.toFixed(2)}</span>}
        </div>

        {/* Target row */}
        {pl.target && (
          <div style={{ background: "rgba(63,185,80,0.10)", border: "1px solid rgba(63,185,80,0.35)", borderRadius: 3, padding: "3px 8px" }}>
            <span style={{ color: C.target, fontWeight: 600 }}>TGT</span>
            <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.target)} ({fmtPct(tgtPct)})</span>
            {rewDol != null && <span style={{ color: C.target }}> · +${fmt(rewDol)}</span>}
          </div>
        )}

        {/* Trail row */}
        {pl.trail && (
          <div style={{ background: "rgba(147,51,234,0.10)", border: "1px solid rgba(147,51,234,0.35)", borderRadius: 3, padding: "3px 8px" }}>
            <span style={{ color: C.trail, fontWeight: 600 }}>TRL</span>
            <span style={{ color: dark ? "#cdd9e5" : "#24292f" }}> {fmt(pl.trail)}</span>
          </div>
        )}
      </div>
    );
  })();

  return (
    // onWheel stopPropagation: prevents the page's overflow-y:auto container
    // from scrolling when the user wheel-zooms the chart.
    <div className="relative w-full" style={{ height }}
      onWheel={(e) => e.stopPropagation()}
    >
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
        {/* Fit-to-content button — centers & scales all visible bars */}
        <button
          title="Fit chart to data (reset zoom & center)"
          onClick={() => {
            if (!chartRef.current) return;
            chartRef.current.timeScale().fitContent();
            // Reset price scale auto-scaling so the full price range is visible
            chartRef.current.priceScale("right").applyOptions({ autoScale: true });
          }}
          style={{
            background: "transparent",
            border: `1px solid var(--border)`,
            borderRadius: 3,
            padding: "1px 5px",
            cursor: "pointer",
            color: "var(--ink-muted)",
            fontSize: 11,
            lineHeight: 1.4,
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

      {/* Position indicator card — appears when a trade is open and toggle is on */}
      {showPositionCard && posCard}

      {/* Chart canvas */}
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
  );
}
