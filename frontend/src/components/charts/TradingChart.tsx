/**
 * TradingChart.tsx — TradingView Lightweight Charts v5 wrapper.
 *
 * Renders candlesticks + optional overlays:
 *   - VWAP line
 *   - Opening Range (high/low dashed bands)
 *   - Trade entry/exit markers (via createSeriesMarkers, LWC v5 API)
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
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  SeriesMarker,
  Time,
} from "lightweight-charts";
import type { Bar, Trade } from "../../lib/api";
import { useThemeStore } from "../../store/theme";

interface Props {
  bars: Bar[];
  trades?: Trade[];
  showVwap?: boolean;
  showOR?: boolean;
  orHigh?: number;
  orLow?: number;
  height?: number;
  ticker?: string;
}

function toTime(iso: string): Time {
  return (new Date(iso).getTime() / 1000) as Time;
}

function colors(dark: boolean) {
  return {
    background:  dark ? "#0d1117" : "#ffffff",
    text:        dark ? "#8b949e" : "#5a6476",
    grid:        dark ? "#21262d" : "#f0f2f7",
    border:      dark ? "#30363d" : "#e2e5ed",
    up:          dark ? "#3fb950" : "#16a34a",
    down:        dark ? "#f85149" : "#dc2626",
    vwap:        dark ? "#58a6ff" : "#2563eb",
    orHigh:      dark ? "#3fb950" : "#16a34a",
    orLow:       dark ? "#f85149" : "#dc2626",
  };
}

export function TradingChart({
  bars,
  trades = [],
  showVwap = true,
  showOR = true,
  orHigh,
  orLow,
  height = 420,
  ticker,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);

  // Use unknown for refs to avoid LWC's overly-narrow generic return from addSeries
  const candleRef  = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const vwapRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const volRef     = useRef<ISeriesApi<"Histogram"> | null>(null);
  const orHighRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const orLowRef   = useRef<ISeriesApi<"Line"> | null>(null);

  const { theme } = useThemeStore();
  const dark = theme === "dark";
  const C = colors(dark);

  // ── Build chart on mount / dark-mode change ────────────────────────────
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

    // LWC v5: chart.addSeries(SeriesDefinition, options)
    // Cast needed because addSeries returns a wide union type
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: C.up, downColor: C.down,
      borderUpColor: C.up, borderDownColor: C.down,
      wickUpColor: C.up, wickDownColor: C.down,
    }) as unknown as ISeriesApi<"Candlestick">;

    volRef.current = chart.addSeries(HistogramSeries, {
      color: C.grid,
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    }) as unknown as ISeriesApi<"Histogram">;
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    vwapRef.current = chart.addSeries(LineSeries, {
      color: C.vwap, lineWidth: 2,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    orHighRef.current = chart.addSeries(LineSeries, {
      color: C.orHigh, lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    orLowRef.current = chart.addSeries(LineSeries, {
      color: C.orLow, lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, crosshairMarkerVisible: false,
    }) as unknown as ISeriesApi<"Line">;

    const ro = new ResizeObserver(() => {
      containerRef.current &&
        chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      vwapRef.current = null;
      volRef.current = null;
      orHighRef.current = null;
      orLowRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, dark]);

  // ── Feed data on bars / overlays change ───────────────────────────────
  useEffect(() => {
    if (!candleRef.current || !bars.length) return;

    candleRef.current.setData(
      bars.map((b) => ({ time: toTime(b.time), open: b.open, high: b.high, low: b.low, close: b.close }))
    );

    volRef.current?.setData(
      bars.map((b) => ({
        time: toTime(b.time), value: b.volume,
        color: b.close >= b.open ? C.up + "55" : C.down + "55",
      }))
    );

    vwapRef.current?.setData(
      showVwap
        ? bars.filter((b) => b.vwap != null).map((b) => ({ time: toTime(b.time), value: b.vwap! }))
        : []
    );

    if (showOR && orHigh != null && orLow != null && bars.length) {
      const first = toTime(bars[0].time);
      const last  = toTime(bars[bars.length - 1].time);
      orHighRef.current?.setData([{ time: first, value: orHigh }, { time: last, value: orHigh }]);
      orLowRef.current?.setData( [{ time: first, value: orLow  }, { time: last, value: orLow  }]);
    } else {
      orHighRef.current?.setData([]);
      orLowRef.current?.setData([]);
    }

    // Trade entry/exit markers
    const markers: SeriesMarker<Time>[] = [];
    for (const t of trades) {
      if (t.entry_time) markers.push({ time: toTime(t.entry_time), position: "belowBar", color: C.vwap, shape: "arrowUp",   text: `BUY ${t.ticker}`, size: 1 });
      if (t.exit_time)  markers.push({ time: toTime(t.exit_time),  position: "aboveBar", color: C.down, shape: "arrowDown", text: `SELL ${t.exit_reason ?? ""}`, size: 1 });
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    createSeriesMarkers(candleRef.current, markers);

    chartRef.current?.timeScale().fitContent();
  }, [bars, trades, showVwap, showOR, orHigh, orLow]);

  return (
    <div className="relative w-full" style={{ height }}>
      {ticker && (
        <div className="absolute top-2 left-3 z-10 text-xs font-mono font-semibold"
             style={{ color: "var(--ink-muted)" }}>
          {ticker}
        </div>
      )}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
