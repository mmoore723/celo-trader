/**
 * KChart.tsx — KLineChart v9 trading chart with drawing tools.
 *
 * Features:
 *   - Drawing toolbar: Select / Trend / H-Line / Ray / Segment / Fibonacci / Parallel / Rect
 *   - TradingView navy dark palette (#131722 bg, teal up, red down)
 *   - Custom VWAP ±1σ indicator (intraday, day-reset)
 *   - RSI + MACD sub-panels (built-in)
 *   - OHLC crosshair legend via direct DOM update
 *   - Locked OR lines and position price-line overlays
 */
import { useEffect, useRef, useState } from "react";
import { init, dispose } from "klinecharts";
import type { Bar, Trade } from "../../lib/api";
import { useThemeStore } from "../../store/theme";
import { registerCustomIndicators } from "./kchartIndicators";
import type { PositionLevels } from "./TradingChart";

registerCustomIndicators(); // idempotent one-time registration

// ── Drawing tool definitions ──────────────────────────────────────────────────
const TOOLS = [
  { key: "",                       icon: "↖",  label: "Select"    },
  { key: "straightLine",           icon: "╲",  label: "Trend"     },
  { key: "horizontalStraightLine", icon: "—",  label: "H-Line"    },
  { key: "rayLine",                icon: "→",  label: "Ray"       },
  { key: "segment",                icon: "╴",  label: "Segment"   },
  { key: "fibonacciLine",          icon: "φ",  label: "Fibonacci" },
  { key: "parallelStraightLine",   icon: "⫽",  label: "Parallel"  },
  { key: "rect",                   icon: "□",  label: "Rectangle" },
];

// ── Component props (compatible with old TradingChart for drop-in swap) ───────
export interface KChartProps {
  bars: Bar[];
  trades?: Trade[];
  showVwap?: boolean;
  showVwapBands?: boolean;
  showOR?: boolean;
  showSwings?: boolean;
  showPositionCard?: boolean;
  showRsi?: boolean;
  showMacd?: boolean;
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  currentOptionPrice?: number | null;
  height?: number;
  ticker?: string;
  /** Epoch ms — chart scrolls so this timestamp appears at the left edge */
  visibleFrom?: number;
}

// ── Build KLineChart style object ─────────────────────────────────────────────
function makeStyles(dark: boolean) {
  const grid   = dark ? "#1e222d" : "#f0f2f7";
  const border = dark ? "#2a2e39" : "#d1d5db";
  const text   = dark ? "#848e9c" : "#5a6476";
  const up     = dark ? "#26a69a" : "#089981";
  const dn     = dark ? "#ef5350" : "#f23645";

  return {
    grid: {
      show: true,
      horizontal: { show: true, size: 1, color: grid, style: "dashed" as const, dashedValue: [4, 2] },
      vertical:   { show: true, size: 1, color: grid, style: "dashed" as const, dashedValue: [4, 2] },
    },
    candle: {
      bar: {
        upColor: up,   downColor: dn,   noChangeColor: text,
        upBorderColor: up, downBorderColor: dn, noChangeBorderColor: text,
        upWickColor:   up, downWickColor: dn,   noChangeWickColor: text,
      },
      priceMark: {
        show: true,
        high: { show: true, color: up,   textSize: 10, textFamily: "monospace", textWeight: "normal", textOffset: 5 },
        low:  { show: true, color: dn,   textSize: 10, textFamily: "monospace", textWeight: "normal", textOffset: 5 },
        last: {
          show: true, upColor: up, downColor: dn, noChangeColor: text,
          line: { show: true, style: "dashed" as const, dashedValue: [4, 4], size: 1 },
          text: { show: true, style: "fill" as const, size: 11, color: "#ffffff", weight: "bold" },
        },
      },
      // Disable built-in candle tooltip — custom DOM legend handles OHLC display
      tooltip: { showRule: "none" as const },
    },
    indicator: {
      bars:  [{ upColor: `${up}44`, downColor: `${dn}44`, noChangeColor: `${text}44`,
                upBorderColor: `${up}44`, downBorderColor: `${dn}44`, noChangeBorderColor: `${text}44` }],
      lines: [
        { size: 2, color: "#2962ff" },          // VWAP line / RSI
        { size: 1, color: "#2962ff88" },         // +1σ
        { size: 1, color: "#2962ff88" },         // -1σ
        { size: 2, color: "#f59e0b" },           // MACD histogram / line
        { size: 1, color: "#e879f9" },           // signal
      ],
      tooltip: { showRule: "always" as const, showName: true, showParams: true,
                 text: { size: 10, color: text, weight: "normal", family: "monospace",
                         marginLeft: 8, marginTop: 4, marginRight: 8, marginBottom: 4 } },
    },
    xAxis: { show: true,
             axisLine: { show: true, color: border, size: 1 },
             tickLine: { show: true, color: border, size: 1, length: 3 },
             tickText: { show: true, color: text, size: 10, family: "monospace", weight: "normal" } },
    yAxis: { show: true,
             axisLine: { show: true, color: border, size: 1 },
             tickLine: { show: true, color: border, size: 1, length: 3 },
             tickText: { show: true, color: text, size: 10, family: "monospace", weight: "normal" } },
    crosshair: {
      show: true,
      horizontal: { show: true,
                    line: { show: true, style: "dashed" as const, dashedValue: [4, 2], size: 1, color: border },
                    text: { show: true, style: "fill" as const, size: 10, color: "#ffffff",
                            weight: "normal", family: "monospace",
                            borderSize: 0, borderRadius: 2, borderColor: up,
                            paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
                            backgroundColor: up } },
      vertical:   { show: true,
                    line: { show: true, style: "dashed" as const, dashedValue: [4, 2], size: 1, color: border },
                    text: { show: true, style: "fill" as const, size: 10, color: dark ? "#e6edf3" : "#1c2128",
                            weight: "normal", family: "monospace",
                            borderSize: 0, borderRadius: 2, borderColor: border,
                            paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
                            backgroundColor: dark ? "#1e222d" : "#f6f8fa" } },
    },
    separator: { size: 1, color: border },
    overlay: {
      line: { size: 1, color: up, style: "solid" as const, dashedValue: [4, 2], smooth: false },
      text: { size: 10, color: text, weight: "normal", family: "monospace",
              style: "fill" as const, borderRadius: 2, borderSize: 0, borderColor: "transparent",
              paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
              backgroundColor: "transparent" },
    },
  };
}

// ── Component ─────────────────────────────────────────────────────────────────
export function KChart({
  bars,
  trades = [],
  showVwap = true,
  showVwapBands = true,
  showOR = true,
  showRsi = true,
  showMacd = true,
  orHigh,
  orLow,
  positionLevels,
  height = 420,
  ticker,
  visibleFrom,
}: KChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<any>(null);
  const ohlcRef      = useRef<HTMLDivElement>(null);
  const [tool, setTool] = useState("");

  const { theme } = useThemeStore();
  const dark = theme === "dark";

  // Color palette shortcuts (must stay in sync with makeStyles)
  const up     = dark ? "#26a69a" : "#089981";
  const dn     = dark ? "#ef5350" : "#f23645";
  const border = dark ? "#2a2e39" : "#d1d5db";
  const text   = dark ? "#848e9c" : "#5a6476";

  // ── Create / destroy chart when theme or indicators change ──────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Ensure container has dimensions before init
    if (el.clientWidth === 0 || el.clientHeight === 0) {
      // wait one frame for layout to complete
      const id = requestAnimationFrame(() => { chartRef.current?.resize(); });
      // still proceed — KLineChart handles 0-sized containers on resize
      return () => cancelAnimationFrame(id);
    }

    const chart = init(el) as any;
    if (!chart) return;               // init returns null if el is null
    chartRef.current = chart;

    // Apply theme styles
    chart.setStyles(makeStyles(dark));
    chart.setOffsetRightDistance(80);

    // Volume in candle pane, RSI/MACD as sub-panels
    // VOL must be in its own pane — KLineChart v9 has no secondary Y-axis,
    // so stacking volume in the candle pane would include volume values
    // (1-3M+) in the price axis range and make candles invisible.
    chart.createIndicator("VOL", false, { id: "vol_pane", height: 56, minHeight: 40 });
    if (showRsi) {
      chart.createIndicator("RSI", false, { id: "rsi_pane", height: 90 });
      // Default RSI shows 3 lines [6,12,24] — override to single period 14
      try { chart.overrideIndicator({ name: "RSI", calcParams: [14] }, "rsi_pane"); } catch (_) {}
    }
    if (showMacd) chart.createIndicator("MACD", false, { id: "macd_pane", height: 100 });

    // 12-hour AM/PM time format for x-axis ticks
    chart.setCustomApi({
      formatDate: (_fmt: unknown, timestamp: number, format: string, _type: unknown) => {
        const d = new Date(timestamp);
        // Time ticks (HH:mm format string) → convert to 12h
        if (format && (format.includes("HH") || format.includes("hh"))) {
          let h = d.getHours();
          const m = String(d.getMinutes()).padStart(2, "0");
          const ampm = h >= 12 ? "PM" : "AM";
          h = h % 12 || 12;
          return `${h}:${m} ${ampm}`;
        }
        // Date ticks → MM/DD
        return `${d.getMonth() + 1}/${d.getDate()}`;
      },
    });

    // OHLC crosshair legend — pure DOM update (no React re-render on mouse move)
    chart.subscribeAction("onCrosshairChange", (data: any) => {
      const el2 = ohlcRef.current;
      if (!el2) return;
      if (!data?.kLineData) { el2.style.opacity = "0"; return; }
      const d = data.kLineData;
      const chg    = d.close - d.open;
      const chgPct = (chg / d.open) * 100;
      const col    = chg >= 0 ? up : dn;
      el2.innerHTML =
        `<span>O</span>&nbsp;<b>${d.open.toFixed(2)}</b>&ensp;` +
        `<span style="color:${up}">H</span>&nbsp;<b>${d.high.toFixed(2)}</b>&ensp;` +
        `<span style="color:${dn}">L</span>&nbsp;<b>${d.low.toFixed(2)}</b>&ensp;` +
        `<span>C</span>&nbsp;<b>${d.close.toFixed(2)}</b>&ensp;` +
        `<span style="color:${col}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)} (${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%)</span>`;
      el2.style.opacity = "1";
    });

    // Auto-resize when container dimensions change
    const ro = new ResizeObserver(() => { chartRef.current?.resize(); });
    ro.observe(el);

    return () => {
      ro.disconnect();
      // chartRef.current may be null if a previous cleanup already ran
      if (chartRef.current && containerRef.current) {
        dispose(containerRef.current);
      }
      chartRef.current = null;
    };
  // Re-run only when visual theme or sub-panel config changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, showRsi, showMacd]);

  // ── Feed bars + manage VWAP/OR/position overlays ───────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Load bars (convert string timestamp → ms epoch)
    if (bars.length > 0) {
      // Filter outlier candles that would crush the y-axis.
      // Compute median close, then drop any bar whose high or low deviates > 12%.
      // 699 vs 751 is ~7% — catches bad data without touching normal intraday swings.
      const closes = bars.map((b) => b.close).sort((a, z) => a - z);
      const medClose = closes[Math.floor(closes.length / 2)];
      const SPIKE_THRESHOLD = 0.12;
      const filtered = bars.filter(
        (b) =>
          Math.abs(b.high - medClose) / medClose < SPIKE_THRESHOLD &&
          Math.abs(b.low  - medClose) / medClose < SPIKE_THRESHOLD
      );
      // Fall back to unfiltered if everything was removed (shouldn't happen)
      const safe = filtered.length > 0 ? filtered : bars;
      chart.applyNewData(
        safe.map((b) => ({
          timestamp: new Date(b.time).getTime(),
          open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume ?? 0,
        }))
      );
      // Always scroll to the most recent data after loading.
      // NOTE: scrollToTimestamp() in KLineChart v9 puts the timestamp at the
      // RIGHT edge (not left), so calling it with visibleFrom scrolled BACKWARD
      // to show old data instead of recent data. Use scrollToRealTime() always.
      chart.scrollToRealTime();
    }

    // VWAP indicator — toggle without recreating the whole chart
    try {
      const hasVwap = !!(chart.getIndicatorByPaneId("candle_pane", "VWAP"));
      if (showVwap && !hasVwap) {
        chart.createIndicator("VWAP", true, { id: "candle_pane" }, () => {
          // override styles inside callback so indicator exists
          chart.overrideIndicator({
            name: "VWAP",
            styles: {
              lines: [
                { color: "#2962ff", size: 2 },
                { color: showVwapBands ? "#2962ff66" : "transparent", size: 1 },
                { color: showVwapBands ? "#2962ff66" : "transparent", size: 1 },
              ],
            },
          }, "candle_pane");
        });
      } else if (!showVwap && hasVwap) {
        chart.removeIndicator("candle_pane", "VWAP");
      } else if (showVwap && hasVwap) {
        // Already exists — just update band visibility
        chart.overrideIndicator({
          name: "VWAP",
          styles: {
            lines: [
              { color: "#2962ff", size: 2 },
              { color: showVwapBands ? "#2962ff66" : "transparent", size: 1 },
              { color: showVwapBands ? "#2962ff66" : "transparent", size: 1 },
            ],
          },
        }, "candle_pane");
      }
    } catch (_) { /* indicator may not be ready yet — will reconcile on next render */ }

    // Clear managed overlays before recreating
    try { chart.removeOverlay({ groupId: "or"  }); } catch (_) { /* no-op */ }
    try { chart.removeOverlay({ groupId: "pos" }); } catch (_) { /* no-op */ }

    // Opening Range horizontal lines
    if (showOR) {
      if (orHigh != null) {
        chart.createOverlay({
          name: "horizontalStraightLine", groupId: "or", lock: true,
          points: [{ value: orHigh }],
          styles: { line: { color: up, size: 2 } },
          needDefaultYAxisFigure: true,
        });
      }
      if (orLow != null) {
        chart.createOverlay({
          name: "horizontalStraightLine", groupId: "or", lock: true,
          points: [{ value: orLow }],
          styles: { line: { color: dn, size: 2 } },
          needDefaultYAxisFigure: true,
        });
      }
    }

    // Position price lines (Entry / Stop / Target / Trail).
    // "horizontalStraightLine" is the correct KLineChart v9 built-in name.
    // "priceLine" is NOT valid — it caused an unknown-overlay rendering artifact
    // (a tall vertical spike) and forced the Y-axis to scale out to the stop price.
    if (positionLevels) {
      const ep = positionLevels.entry;
      const LEVELS = [
        { val: ep,                            col: "#eab308", sz: 2 },
        { val: positionLevels.stop,           col: dn,        sz: 1 },
        { val: positionLevels.target,         col: up,        sz: 1 },
        { val: (positionLevels as any).trail, col: "#9333ea", sz: 1 },
      ];
      LEVELS.forEach(({ val, col, sz }) => {
        if (!val || val <= 0) return;
        try {
          chart.createOverlay({
            name: "horizontalStraightLine", groupId: "pos", lock: true,
            points: [{ value: val }],
            styles: { line: { color: col, size: sz } },
            needDefaultYAxisFigure: true,   // shows price label on Y-axis
          });
        } catch (_) { /* skip if overlay fails */ }
      });
    }

  }, [bars, showVwap, showVwapBands, showOR, orHigh, orLow, positionLevels]);

  // trades/visibleFrom props kept on interface so parent doesn't need to change.
  // Trade markers temporarily disabled (custom overlay was corrupting KLineChart).
  // visibleFrom scroll disabled (scrollToTimestamp put it at RIGHT edge, backwards).
  void trades; void visibleFrom;

  // ── Activate drawing tool on toolbar click ─────────────────────────────────
  useEffect(() => {
    if (tool && chartRef.current) {
      try { chartRef.current.createOverlay(tool); } catch (_) { /* not in dom yet */ }
    }
  }, [tool]);

  // ESC exits drawing mode
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setTool(""); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col w-full">
      {/* ── Drawing toolbar ── */}
      <div className="flex items-center gap-1 px-2 py-1.5 flex-wrap"
           style={{ borderBottom: `1px solid ${border}`, background: dark ? "#1a1f2e" : "#f6f8fa" }}>
        {TOOLS.map((t) => (
          <button
            key={t.key}
            title={t.label}
            className={`btn btn-sm ${tool === t.key ? "btn-primary" : "btn-ghost"}`}
            style={{ fontFamily: "monospace" }}
            onClick={() => setTool(tool === t.key ? "" : t.key)}
          >
            <span>{t.icon}</span>
            <span className="text-[10px] hidden sm:inline ml-1">{t.label}</span>
          </button>
        ))}
        <div style={{ width: 1, height: 18, background: border, margin: "0 4px" }} />
        <button
          className="btn btn-ghost btn-sm"
          title="Clear all drawings"
          onClick={() => { chartRef.current?.removeOverlay(); setTool(""); }}
        >
          🗑
        </button>
        {tool && (
          <span className="ml-2 text-[10px] italic" style={{ color: text }}>
            Click chart · ESC to cancel · DEL removes selected
          </span>
        )}
      </div>

      {/* ── Chart area ── */}
      <div className="relative" style={{ height }}>
        {/* Ticker + OHLC crosshair legend overlay */}
        <div className="absolute top-2 left-3 z-10 flex items-center gap-3 pointer-events-none"
             style={{ fontFamily: "monospace" }}>
          {ticker && (
            <span className="text-sm font-bold tracking-widest"
                  style={{ color: dark ? "#e6edf3" : "#1c2128" }}>
              {ticker}
            </span>
          )}
          <div
            ref={ohlcRef}
            className="text-xs"
            style={{ opacity: 0, color: text, transition: "opacity 0.1s" }}
          />
        </div>

        {/* KLineChart mount point — must have explicit 100% dimensions */}
        <div
          ref={containerRef}
          style={{ width: "100%", height: "100%", background: dark ? "#131722" : "#ffffff", position: "relative" }}
        />
      </div>
    </div>
  );
}
