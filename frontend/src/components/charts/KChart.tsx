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
  /** Active timeframe — used to set natural bar spacing ("1Min"|"5Min"|"15Min"|"1Hour") */
  tf?: string;
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
  tf = "5Min",
}: KChartProps) {
  const containerRef  = useRef<HTMLDivElement>(null);
  const chartRef      = useRef<any>(null);
  const ohlcRef       = useRef<HTMLDivElement>(null);
  // Track the last TF that bar-spacing was applied for.
  // setBarSpace should only fire on TF change, NOT on every 60-second data refresh —
  // otherwise the user's zoom is reset every minute and the chart feels frozen/broken.
  const lastSpacingTf = useRef<string>("");
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
    // Explicitly enable zoom and scroll (required in v9 — not on by default)
    chart.setZoomEnabled(true);
    chart.setScrollEnabled(true);

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

    // Wheel zoom — native listener so preventDefault() stops page scroll.
    // setZoomEnabled(true) handles pinch/trackpad but does NOT reliably hook
    // mouse-wheel events in all browsers; a native handler is the reliable fix.
    // Placed here (inside chart init effect) so it's tied to the chart lifetime.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (!chartRef.current) return;
      const rect  = el.getBoundingClientRect();
      const scale = e.deltaY < 0 ? 1.1 : 0.9;
      try {
        chartRef.current.zoomAtCoordinate(scale, {
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
        });
      } catch (_) {}
    };
    el.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      el.removeEventListener("wheel", onWheel);
      ro.disconnect();
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
      // Statistical outlier removal using Median Absolute Deviation (MAD).
      // The 699.05 spike has open≈close≈699, so wick-clipping (prior approach)
      // doesn't help — the whole bar body is the bad data point. MAD-based
      // filtering removes entire bars that are statistical impossibilities.
      //
      // Z = |value - median| / MAD  — anything ≥ 8 is a data error.
      // Example: med=751, MAD≈1 → 699.05 gives Z≈52 → removed.
      // Legitimate crash bars on monthly charts: med≈500, MAD≈20 → Z≈1.5 → kept.
      const sortedCloses = bars.map((b) => b.close).sort((a, z) => a - z);
      const med    = sortedCloses[Math.floor(sortedCloses.length / 2)];
      const madArr = sortedCloses.map((c) => Math.abs(c - med)).sort((a, z) => a - z);
      const mad    = madArr[Math.floor(madArr.length / 2)] || med * 0.001;
      const Z_CUT  = 8;
      const filtered = bars.filter(
        (b) =>
          Math.abs(b.low   - med) / mad < Z_CUT &&
          Math.abs(b.high  - med) / mad < Z_CUT &&
          Math.abs(b.close - med) / mad < Z_CUT   // catch bars where the whole body is bad
      );
      // Fall back to raw only if the filter eliminated EVERYTHING (true data error)
      const safe = filtered.length > 0 ? filtered : bars;
      chart.applyNewData(
        safe.map((b) => ({
          timestamp: new Date(b.time).getTime(),
          open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume ?? 0,
        }))
      );
      // Only reset bar spacing when the timeframe actually changes.
      // On 60-second live refetches (same TF), skip setBarSpace so the user's
      // zoom level is preserved. Calling setBarSpace every minute makes the chart
      // feel frozen because it resets zoom after every data refresh.
      if (tf !== lastSpacingTf.current) {
        const naturalCount: Record<string, number> = {
          "1Min": 240, "5Min": 100, "15Min": 50, "1Hour": 30,
        };
        const barsInView = Math.min(safe.length, naturalCount[tf] ?? 100);
        const containerW = containerRef.current?.clientWidth ?? 900;
        const barSpace   = Math.max(2, Math.min(30, (containerW - 70) / barsInView));
        try { chart.setBarSpace(barSpace); } catch (_) {}
        lastSpacingTf.current = tf;
      }
      // Scroll to latest bar. Use a small delay so applyNewData finishes
      // rendering before we scroll — avoids landing at bar-0 on fast refreshes.
      setTimeout(() => {
        try { chartRef.current?.scrollToRealTime(); } catch (_) {}
      }, 50);
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

  }, [bars, tf, showVwap, showVwapBands, showOR, orHigh, orLow, positionLevels]);

  // trades/visibleFrom props kept on interface so parent doesn't need to change.
  // Trade markers temporarily disabled (custom overlay was corrupting KLineChart).
  // visibleFrom scroll disabled (scrollToTimestamp put it at RIGHT edge, backwards).
  void trades; void visibleFrom;

  // Wheel zoom is registered inside the chart-init useEffect above,
  // so it's automatically cleaned up when the chart is destroyed.

  // ── Activate drawing tool ─────────────────────────────────────────────────
  // In KLineChart v9.8.12, createOverlay(name) enters interactive draw mode
  // when passed a string — the user then clicks to place points.
  // startDraw / stopDraw DO NOT EXIST in v9 — calling them silently throws.
  // Deselecting a tool (tool="") just stops activating new draws; the user
  // completes or cancels the in-progress one naturally.
  useEffect(() => {
    if (!chartRef.current || !tool) return;
    try { chartRef.current.createOverlay(tool); } catch (_) {}
  }, [tool]);

  // ESC returns to select mode; DEL removes the hovered/selected overlay
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setTool(""); // return to select mode — no stopDraw, it doesn't exist in v9
      }
      if ((e.key === "Delete" || e.key === "Backspace") && !tool) {
        // Remove overlays only when not actively drawing (to avoid cutting a draw in progress)
        try { chartRef.current?.removeOverlay(); } catch (_) {}
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    // stopPropagation on wheel so the parent page-scroll container doesn't consume
    // the event before KLineChart's built-in scroll-to-zoom handler receives it.
    <div className="flex flex-col w-full" onWheel={(e) => e.stopPropagation()}>
      {/* ── Drawing toolbar ── */}
      <div className="flex items-center gap-1 px-2 py-1.5 flex-wrap"
           style={{ borderBottom: `1px solid ${border}`, background: dark ? "#1a1f2e" : "#f6f8fa" }}>
        {TOOLS.map((t) => (
          <button
            key={t.key}
            title={t.label}
            className={`btn btn-sm ${tool === t.key ? "btn-primary" : "btn-ghost"}`}
            style={{ fontFamily: "monospace" }}
            onClick={() => {
              setTool(tool === t.key ? "" : t.key);
            }}
          >
            <span>{t.icon}</span>
            <span className="text-[10px] hidden sm:inline ml-1">{t.label}</span>
          </button>
        ))}
        <div style={{ width: 1, height: 18, background: border, margin: "0 4px" }} />
        {/* Zoom in / out buttons — backup for trackpads that don't scroll-zoom */}
        <button
          className="btn btn-ghost btn-sm"
          title="Zoom in (scroll up also works)"
          onClick={() => {
            const el = containerRef.current;
            if (!chartRef.current || !el) return;
            chartRef.current.zoomAtCoordinate(1.2, { x: el.clientWidth / 2, y: el.clientHeight / 2 });
          }}
        >＋</button>
        <button
          className="btn btn-ghost btn-sm"
          title="Zoom out (scroll down also works)"
          onClick={() => {
            const el = containerRef.current;
            if (!chartRef.current || !el) return;
            chartRef.current.zoomAtCoordinate(0.8, { x: el.clientWidth / 2, y: el.clientHeight / 2 });
          }}
        >－</button>
        <div style={{ width: 1, height: 18, background: border, margin: "0 4px" }} />
        <button
          className="btn btn-ghost btn-sm"
          title="Clear all drawings"
          onClick={() => { try { chartRef.current?.removeOverlay(); } catch (_) {} setTool(""); }}
        >
          🗑
        </button>
        {tool && (
          <span className="ml-2 text-[10px] italic" style={{ color: text }}>
            Click chart to draw · ESC to cancel
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
