/**
 * TradingChart.tsx — TradingView Lightweight Charts v5 wrapper.
 *
 * Overlays ported from lightweight_chart.py (Streamlit version):
 *   - Candlesticks with gold highlight on breakout-volume bars (RVOL ≥ 2×)
 *   - Volume histogram with rolling-average line + 200% gate level
 *   - VWAP line (blue)
 *   - VWAP ±1σ / ±2σ bands (lighter fills)
 *   - Opening Range high/low dashed lines
 *   - Swing structure markers: SH / SL computed from local pivots
 *   - Open position price lines: Entry (yellow) / Stop (red) / Target (green) / Trail (purple)
 *   - Trade entry/exit markers with floating tooltip on hover
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
}

interface Props {
  bars: Bar[];
  trades?: Trade[];
  showVwap?: boolean;
  showVwapBands?: boolean;
  showOR?: boolean;
  showSwings?: boolean;
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  height?: number;
  ticker?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toTime(iso: string): Time {
  // LWC expects epoch seconds for intraday data
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
    vwapBand1:    dark ? "#58a6ffaa" : "#2563eb77",  // ±1σ — more visible
    vwapBand2:    dark ? "#58a6ff55" : "#2563eb44",  // ±2σ
    orHigh:       dark ? "#4ade80" : "#16a34a",      // bright green
    orLow:        dark ? "#f87171" : "#dc2626",      // bright red
    volAvg:       dark ? "#9ca3af" : "#6b7280",
    volGate:      dark ? "#f59e0b55" : "#d9770644",  // 200% gate — amber
    swingH:       dark ? "#f85149" : "#dc2626",      // SH / LH — red
    swingL:       dark ? "#3fb950" : "#16a34a",      // SL / HL — green
    breakout:     "#f59e0b",                          // gold candle border
    entry:        "#eab308",                          // yellow
    stop:         "#dc2626",                          // red
    target:       "#16a34a",                          // green
    trail:        "#9333ea",                          // purple
    buyMarker:    "#38bdf8",                          // sky blue
    sellMarker:   "#e879f9",                          // pink/purple
  };
}

// ─── Pivot swing detection ─────────────────────────────────────────────────
// Returns simple SH/SL: a bar is an SH if its high is higher than the
// `lookback` bars on each side, SL if its low is lower.
interface SwingPoint {
  idx: number;
  time: Time;
  price: number;
  kind: "SH" | "SL";
}

function detectSwings(bars: Bar[], lookback = 3): SwingPoint[] {
  const out: SwingPoint[] = [];
  for (let i = lookback; i < bars.length - lookback; i++) {
    const b = bars[i];
    let isHigh = true, isLow = true;
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue;
      if (bars[j].high >= b.high) isHigh = false;
      if (bars[j].low  <= b.low)  isLow  = false;
    }
    if (isHigh) out.push({ idx: i, time: toTime(b.time), price: b.high, kind: "SH" });
    if (isLow)  out.push({ idx: i, time: toTime(b.time), price: b.low,  kind: "SL" });
  }
  return out;
}

// ─── Rolling mean ─────────────────────────────────────────────────────────
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
  const orHighRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const orLowRef     = useRef<ISeriesApi<"Line"> | null>(null);

  // price-line refs (position levels)
  const priceLineRefs = useRef<IPriceLine[]>([]);

  // tooltip div ref
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const { theme } = useThemeStore();
  const dark = theme === "dark";
  const C = colors(dark);

  // ── Build chart on mount / theme change ─────────────────────────────────
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
      rightPriceScale: { borderColor: C.border },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: false,
      },
    });
    chartRef.current = chart;

    // ── Candles ───────────────────────────────────────────────────────────
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor:        C.up,
      downColor:      C.down,
      borderUpColor:  C.up,
      borderDownColor: C.down,
      wickUpColor:    C.up,
      wickDownColor:  C.down,
    }) as unknown as ISeriesApi<"Candlestick">;

    // ── Volume histogram ───────────────────────────────────────────────────
    volRef.current = chart.addSeries(HistogramSeries, {
      color: C.grid,
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    }) as unknown as ISeriesApi<"Histogram">;
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    // Volume rolling average on its own overlay scale
    volAvgRef.current = chart.addSeries(LineSeries, {
      color: C.volAvg, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── VWAP ──────────────────────────────────────────────────────────────
    vwapRef.current = chart.addSeries(LineSeries, {
      color: C.vwap, lineWidth: 2,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── VWAP bands (±2σ outer, ±1σ inner) ────────────────────────────────
    vwapU2Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand2, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    vwapL2Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand2, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    vwapU1Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand1, lineWidth: 2, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    vwapL1Ref.current = chart.addSeries(LineSeries, {
      color: C.vwapBand1, lineWidth: 2, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── Opening Range — solid + thick so they're clearly visible ──────────
    orHighRef.current = chart.addSeries(LineSeries, {
      color: C.orHigh, lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    orLowRef.current = chart.addSeries(LineSeries, {
      color: C.orLow, lineWidth: 2, lineStyle: LineStyle.Solid,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    // ── Resize observer ───────────────────────────────────────────────────
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
      orHighRef.current   = null;
      orLowRef.current    = null;
      priceLineRefs.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, dark]);

  // ── Feed data & overlays on bars / props change ────────────────────────
  useEffect(() => {
    if (!candleRef.current || !bars.length) return;

    // Compute per-bar breakout flag (RVOL ≥ 2.0 = gold candle)
    const breakoutThreshold = 2.0;

    // ── Candles ───────────────────────────────────────────────────────────
    candleRef.current.setData(
      bars.map((b) => {
        const isBreakout = (b.rvol ?? 0) >= breakoutThreshold;
        return {
          time:             toTime(b.time),
          open:             b.open,
          high:             b.high,
          low:              b.low,
          close:            b.close,
          // Gold border on breakout-volume bars
          borderUpColor:    isBreakout ? C.breakout : C.up,
          borderDownColor:  isBreakout ? C.breakout : C.down,
          wickUpColor:      isBreakout ? C.breakout : C.up,
          wickDownColor:    isBreakout ? C.breakout : C.down,
        };
      })
    );

    // ── Volume + rolling average ──────────────────────────────────────────
    const vols = bars.map((b) => b.volume);
    const avgWindow = Math.min(20, bars.length);
    const avgVol = rollingMean(vols, avgWindow);

    volRef.current?.setData(
      bars.map((b) => {
        // Gold tint on breakout bars, else standard up/down colour
        const isBreakout = (b.rvol ?? 0) >= breakoutThreshold;
        const base = b.close >= b.open ? C.up : C.down;
        const color = isBreakout ? C.breakout + "bb" : base + "55";
        return { time: toTime(b.time), value: b.volume, color };
      })
    );

    volAvgRef.current?.setData(
      bars
        .map((b, i) => avgVol[i] != null ? { time: toTime(b.time), value: avgVol[i]! } : null)
        .filter(Boolean) as { time: Time; value: number }[]
    );

    // ── VWAP line ─────────────────────────────────────────────────────────
    vwapRef.current?.setData(
      showVwap
        ? bars.filter((b) => b.vwap != null).map((b) => ({ time: toTime(b.time), value: b.vwap! }))
        : []
    );

    // ── VWAP bands ────────────────────────────────────────────────────────
    if (showVwap && showVwapBands) {
      vwapU1Ref.current?.setData(
        bars.filter((b) => b.vwap_upper1 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_upper1! }))
      );
      vwapL1Ref.current?.setData(
        bars.filter((b) => b.vwap_lower1 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_lower1! }))
      );
      vwapU2Ref.current?.setData(
        bars.filter((b) => b.vwap_upper2 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_upper2! }))
      );
      vwapL2Ref.current?.setData(
        bars.filter((b) => b.vwap_lower2 != null).map((b) => ({ time: toTime(b.time), value: b.vwap_lower2! }))
      );
    } else {
      vwapU1Ref.current?.setData([]);
      vwapL1Ref.current?.setData([]);
      vwapU2Ref.current?.setData([]);
      vwapL2Ref.current?.setData([]);
    }

    // ── Opening Range ─────────────────────────────────────────────────────
    if (showOR && orHigh != null && orLow != null && bars.length) {
      const first = toTime(bars[0].time);
      const last  = toTime(bars[bars.length - 1].time);
      orHighRef.current?.setData([{ time: first, value: orHigh }, { time: last, value: orHigh }]);
      orLowRef.current?.setData( [{ time: first, value: orLow  }, { time: last, value: orLow  }]);
    } else {
      orHighRef.current?.setData([]);
      orLowRef.current?.setData([]);
    }

    // ── Swing structure markers ────────────────────────────────────────────
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

    // Swing SH / SL markers (if enabled)
    if (showSwings) {
      const swings = detectSwings(bars, 3);
      for (const sw of swings) {
        tradeMarkers.push({
          time:     sw.time,
          position: sw.kind === "SH" ? "aboveBar" : "belowBar",
          color:    sw.kind === "SH" ? C.swingH : C.swingL,
          shape:    sw.kind === "SH" ? "arrowDown" : "arrowUp",
          text:     sw.kind,
          size:     0,   // tiny — doesn't compete with trade markers
        });
      }
    }

    tradeMarkers.sort((a, b) => (a.time as number) - (b.time as number));
    createSeriesMarkers(candleRef.current, tradeMarkers);

    // ── Position price lines ──────────────────────────────────────────────
    // Remove old lines first
    if (candleRef.current) {
      for (const pl of priceLineRefs.current) {
        try { candleRef.current.removePriceLine(pl); } catch (_) { /* already removed */ }
      }
      priceLineRefs.current = [];

      if (positionLevels) {
        const defs: { key: keyof PositionLevels; color: string; label: string; dash: boolean }[] = [
          { key: "entry",  color: C.entry,  label: "Entry",  dash: false },
          { key: "stop",   color: C.stop,   label: "Stop",   dash: false },
          { key: "target", color: C.target, label: "Target", dash: false },
          { key: "trail",  color: C.trail,  label: "Trail",  dash: true  },
        ];
        for (const def of defs) {
          const price = positionLevels[def.key];
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

    // Build a lookup of timestamp → trade info
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
      const ts = param.time as number;
      const label = lookup.get(ts);
      if (!label) { tt.style.display = "none"; return; }
      tt.textContent = label;
      tt.style.display = "block";
    };

    chart.subscribeCrosshairMove(handleCrosshair);
    return () => chart.unsubscribeCrosshairMove(handleCrosshair);
  }, [trades]);

  return (
    <div className="relative w-full" style={{ height }}>
      {/* Ticker label */}
      {ticker && (
        <div className="absolute top-2 left-3 z-10 text-xs font-mono font-semibold"
             style={{ color: "var(--ink-muted)" }}>
          {ticker}
        </div>
      )}

      {/* Overlay legend */}
      <div className="absolute top-2 right-3 z-10 flex gap-2 text-[10px] font-mono select-none pointer-events-none"
           style={{ color: "var(--ink-muted)" }}>
        {showVwap && <span style={{ color: C.vwap }}>VWAP</span>}
        {showOR   && <span style={{ color: C.orHigh }}>OR▲</span>}
        {showOR   && <span style={{ color: C.orLow  }}>OR▼</span>}
        {positionLevels?.entry  && <span style={{ color: C.entry  }}>ENT</span>}
        {positionLevels?.stop   && <span style={{ color: C.stop   }}>STP</span>}
        {positionLevels?.target && <span style={{ color: C.target }}>TGT</span>}
        {positionLevels?.trail  && <span style={{ color: C.trail  }}>TRL</span>}
      </div>

      {/* Chart canvas */}
      <div ref={containerRef} className="w-full h-full" />

      {/* Crosshair trade tooltip */}
      <div
        ref={tooltipRef}
        style={{
          display:    "none",
          position:   "absolute",
          bottom:     40,
          left:       60,
          background: dark ? "#1c2128" : "#f6f8fa",
          border:     `1px solid ${C.border}`,
          borderRadius: 4,
          padding:    "4px 8px",
          fontSize:   11,
          fontFamily: "JetBrains Mono, monospace",
          color:      C.text,
          pointerEvents: "none",
          zIndex:     20,
        }}
      />
    </div>
  );
}
