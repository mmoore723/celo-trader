/**
 * KChart.tsx — KLineChart v9 chart replacing LightweightCharts.
 *
 * Gains over the old chart:
 *   - Full drawing toolbar (trend line, H-line, ray, fibonacci, rectangle, parallel)
 *   - Built-in RSI + MACD sub-panels
 *   - Custom VWAP ±1σ indicator (computed intraday)
 *   - TradingView navy dark palette
 *   - OHLC crosshair legend (O/H/L/C + delta)
 *   - Locked position / OR price-line overlays
 */
import { useEffect, useRef, useState } from "react";
import { init, dispose } from "klinecharts";
import type { Bar, Trade } from "../../lib/api";
import { useThemeStore } from "../../store/theme";
import { registerCustomIndicators } from "./kchartIndicators";
import type { PositionLevels } from "./TradingChart";

registerCustomIndicators(); // idempotent global registration

// ── Drawing tools ─────────────────────────────────────────────────────────────
const TOOLS = [
  { key: "",                       icon: "↖", label: "Select"     },
  { key: "straightLine",           icon: "╲", label: "Trend"      },
  { key: "horizontalStraightLine", icon: "—", label: "H-Line"     },
  { key: "rayLine",                icon: "→", label: "Ray"        },
  { key: "segment",                icon: "╴", label: "Segment"    },
  { key: "fibonacciLine",          icon: "φ", label: "Fibonacci"  },
  { key: "parallelStraightLine",   icon: "⫽", label: "Parallel"   },
  { key: "rect",                   icon: "□", label: "Rectangle"  },
];

// ── Props (same interface as TradingChart for a drop-in swap) ─────────────────
interface Props {
  bars: Bar[];
  trades?: Trade[];
  showVwap?: boolean;
  showVwapBands?: boolean;
  showOR?: boolean;
  showSwings?: boolean;       // not yet implemented in KLineChart — accepted but ignored
  showPositionCard?: boolean; // position lines always show when positionLevels provided
  showRsi?: boolean;
  showMacd?: boolean;
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  currentOptionPrice?: number | null;
  height?: number;
  ticker?: string;
}

// ── Color palette (TradingView dark / light) ──────────────────────────────────
function pal(dark: boolean) {
  return {
    bg:     dark ? "#131722" : "#ffffff",
    grid:   dark ? "#1e222d" : "#f0f2f7",
    border: dark ? "#2a2e39" : "#e2e5ed",
    text:   dark ? "#848e9c" : "#5a6476",
    up:     dark ? "#26a69a" : "#089981",   // TradingView teal
    dn:     dark ? "#ef5350" : "#f23645",   // TradingView red
    vwap:   "#2962ff",
    entry:  "#eab308",
    stop:   "#ef5350",
    target: "#26a69a",
    trail:  "#9333ea",
  };
}

export function KChart({
  bars, trades: _trades = [],
  showVwap = true, showVwapBands = true,
  showOR = true, showRsi = true, showMacd = true,
  orHigh, orLow, positionLevels,
  height = 420, ticker,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<any>(null);
  const ohlcRef      = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState("");

  const { theme } = useThemeStore();
  const dark = theme === "dark";
  const c    = pal(dark);

  // ── Create chart (recreate on theme / panel toggle) ───────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = init(containerRef.current) as any;
    chartRef.current = chart;

    chart.setTimezone("America/New_York");
    chart.setOffsetRightDistance(80);  // breathing room after last candle

    // TradingView-style theme
    chart.setStyles({
      grid: {
        horizontal: { color: c.grid, size: 1, style: "dashed", dashedValue: [4, 2] },
        vertical:   { color: c.grid, size: 1, style: "dashed", dashedValue: [4, 2] },
      },
      candle: {
        bar: {
          upColor: c.up, downColor: c.dn, noChangeColor: c.text,
          upBorderColor: c.up, downBorderColor: c.dn, noChangeBorderColor: c.text,
          upWickColor: c.up, downWickColor: c.dn, noChangeWickColor: c.text,
        },
        priceMark: {
          high: { show: true, color: c.up,  textSize: 10 },
          low:  { show: true, color: c.dn,  textSize: 10 },
          last: {
            show: true, upColor: c.up, downColor: c.dn, noChangeColor: c.text,
            line: { show: true, style: "dashed", dashedValue: [4, 4], size: 1, color: c.border },
            text: { show: true, style: "fill",   size: 11, color: "#ffffff",
                    paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2, borderRadius: 2 },
          },
        },
        tooltip: {
          showRule: "always", showType: "standard",
          text: { color: c.text, size: 11, family: "JetBrains Mono, monospace",
                  marginLeft: 8, marginTop: 4, marginRight: 8, marginBottom: 4 },
        },
      },
      indicator: {
        ohlc: { upColor: `${c.up}aa`, downColor: `${c.dn}aa`, noChangeColor: `${c.text}aa` },
        bars:  [{ upColor: `${c.up}44`, downColor: `${c.dn}44`, noChangeColor: `${c.text}44` }],
        // lines[0] = VWAP, RSI; lines[1] = +1σ; lines[2] = -1σ; lines[3] = MACD; lines[4] = signal
        lines: [
          { color: c.vwap,           size: 2 },
          { color: `${c.vwap}77`,    size: 1 },
          { color: `${c.vwap}77`,    size: 1 },
          { color: "#f59e0b",        size: 2 },
          { color: "#e879f9",        size: 1 },
        ],
        tooltip: { showRule: "always", text: { color: c.text, size: 10,
                   family: "JetBrains Mono, monospace",
                   marginLeft: 8, marginTop: 4, marginRight: 8, marginBottom: 4 } },
      },
      xAxis: { tickText: { color: c.text, size: 10, family: "JetBrains Mono, monospace" },
               axisLine: { color: c.border }, tickLine: { color: c.border } },
      yAxis: { tickText: { color: c.text, size: 10, family: "JetBrains Mono, monospace" },
               axisLine: { color: c.border }, tickLine: { color: c.border } },
      crosshair: {
        horizontal: { line: { color: c.border },
                      text: { color: "#fff", backgroundColor: c.up } },
        vertical:   { line: { color: c.border },
                      text: { color: "#fff", backgroundColor: dark ? c.bg : c.border } },
      },
      separator: { color: c.border },
    });

    // Volume in main pane (bottom 15%) + RSI + MACD sub-panels
    chart.createIndicator("VOL",  false, { id: "candle_pane" });
    if (showRsi)  chart.createIndicator("RSI",  false, { id: "rsi_pane",  height: 90,  minHeight: 60 });
    if (showMacd) chart.createIndicator("MACD", false, { id: "macd_pane", height: 100, minHeight: 60 });

    // OHLC crosshair legend — pure DOM update, no React re-render
    chart.subscribeAction("onCrosshairChange", (data: any) => {
      const el = ohlcRef.current;
      if (!el || !data?.kLineData) { if (el) el.style.opacity = "0"; return; }
      const d  = data.kLineData;
      const chg    = d.close - d.open;
      const chgPct = (chg / d.open) * 100;
      const col    = chg >= 0 ? c.up : c.dn;
      el.innerHTML =
        `<span style="color:${c.text}">O</span>&nbsp;<b>${d.open.toFixed(2)}</b>&emsp;` +
        `<span style="color:${c.up}">H</span>&nbsp;<b>${d.high.toFixed(2)}</b>&emsp;` +
        `<span style="color:${c.dn}">L</span>&nbsp;<b>${d.low.toFixed(2)}</b>&emsp;` +
        `<span style="color:${c.text}">C</span>&nbsp;<b>${d.close.toFixed(2)}</b>&emsp;` +
        `<span style="color:${col}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}`
        + ` (${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%)</span>`;
      el.style.opacity = "1";
    });

    // Auto-resize when container width changes
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(containerRef.current!);

    return () => {
      ro.disconnect();
      dispose(containerRef.current!);
      chartRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, showRsi, showMacd]);

  // ── Feed data + manage overlays on bars / prop changes ────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !bars.length) return;

    chart.applyNewData(bars.map((b) => ({
      timestamp: new Date(b.time).getTime(),
      open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
    })));

    // VWAP — toggle by removing/creating (getIndicatorByPaneId returns null when absent)
    const hasVwap = !!chart.getIndicatorByPaneId("candle_pane", "VWAP");
    if (showVwap && !hasVwap) chart.createIndicator("VWAP", true, { id: "candle_pane" });
    if (!showVwap && hasVwap) chart.removeIndicator("candle_pane", "VWAP");
    if (showVwap) {
      chart.overrideIndicator({
        name: "VWAP",
        styles: {
          lines: [
            { color: c.vwap,                                        size: 2 },
            { color: showVwapBands ? `${c.vwap}88` : "transparent", size: 1 },
            { color: showVwapBands ? `${c.vwap}88` : "transparent", size: 1 },
          ],
        },
      }, "candle_pane");
    }

    // Remove managed overlays then recreate (cleanly handles prop changes)
    chart.removeOverlay({ groupId: "pos" });
    chart.removeOverlay({ groupId: "or"  });

    // Opening Range lines
    if (showOR) {
      if (orHigh) chart.createOverlay({ name: "horizontalStraightLine", groupId: "or",
        lock: true, points: [{ value: orHigh }],
        styles: { line: { color: c.up, size: 2 } }, needDefaultYAxisFigure: true });
      if (orLow)  chart.createOverlay({ name: "horizontalStraightLine", groupId: "or",
        lock: true, points: [{ value: orLow  }],
        styles: { line: { color: c.dn, size: 2 } }, needDefaultYAxisFigure: true });
    }

    // Position price lines (Entry / Stop / Target / Trail)
    if (positionLevels) {
      const ep = positionLevels.entry;
      [
        { val: positionLevels.entry,  col: c.entry,  sz: 2, label: "Entry"  },
        { val: positionLevels.stop,   col: c.stop,   sz: 1, label: "Stop"   },
        { val: positionLevels.target, col: c.target, sz: 1, label: "Target" },
        { val: positionLevels.trail,  col: c.trail,  sz: 1, label: "Trail"  },
      ].forEach(({ val, col, sz, label }) => {
        if (!val || val <= 0) return;
        const pct = ep && ep !== val
          ? ` (${((val - ep) / ep * 100).toFixed(1)}%)` : "";
        chart.createOverlay({ name: "priceLine", groupId: "pos", lock: true,
          points:     [{ value: val }],
          styles:     { line: { color: col, size: sz } },
          extendData: `${label} $${val.toFixed(2)}${pct}`,
        });
      });
    }
  }, [bars, showVwap, showVwapBands, showOR, orHigh, orLow, positionLevels]);

  // ── Activate drawing tool ─────────────────────────────────────────────────
  useEffect(() => {
    if (tool && chartRef.current) chartRef.current.createOverlay(tool);
  }, [tool]);

  // ESC cancels active draw
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setTool(""); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  // ── JSX ───────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col w-full" onWheel={(e) => e.stopPropagation()}>
      {/* Drawing toolbar */}
      <div className="flex items-center gap-1 px-2 py-1.5 flex-wrap"
           style={{ borderBottom: `1px solid ${c.border}`, background: dark ? "#1a1f2e" : "#f6f8fa" }}>
        {TOOLS.map((t) => (
          <button key={t.key}
            className={`btn btn-sm ${tool === t.key ? "btn-primary" : "btn-ghost"}`}
            title={t.label}
            style={{ fontFamily: "monospace", gap: 3 }}
            onClick={() => setTool(tool === t.key ? "" : t.key)}>
            <span>{t.icon}</span>
            <span className="text-[10px] hidden sm:inline">{t.label}</span>
          </button>
        ))}
        <div style={{ width: 1, height: 18, background: c.border, margin: "0 4px" }} />
        <button className="btn btn-ghost btn-sm text-xs" title="Clear all drawings"
          onClick={() => { chartRef.current?.removeOverlay(); setTool(""); }}>
          🗑
        </button>
        {tool && (
          <span className="text-[10px] ml-2 italic" style={{ color: c.text }}>
            Click chart · ESC cancel · DEL remove selected
          </span>
        )}
      </div>

      {/* Chart area */}
      <div className="relative" style={{ height }}>
        {/* Ticker + OHLC legend */}
        <div className="absolute top-2 left-3 z-10 flex items-center gap-3 pointer-events-none"
             style={{ fontFamily: "JetBrains Mono, monospace" }}>
          {ticker && (
            <span className="text-sm font-bold"
                  style={{ color: dark ? "#e6edf3" : "#1c2128", letterSpacing: "0.05em" }}>
              {ticker}
            </span>
          )}
          <div ref={ohlcRef} className="text-xs flex items-center gap-1"
               style={{ opacity: 0, color: c.text, transition: "opacity 0.1s" }} />
        </div>
        <div ref={containerRef} className="w-full h-full" style={{ background: c.bg }} />
      </div>
    </div>
  );
}
