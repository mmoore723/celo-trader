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
import type { Bar, Trade, ChartAnnotation } from "../../lib/api";
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
  /** Bot-generated overlays: FVG zones, BOS hlines, signal/veto markers */
  annotations?: ChartAnnotation[];
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
  annotations = [],
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

    // Initialize chart regardless of current container dimensions.
    // If the container hasn't been laid out yet (clientWidth === 0) the
    // ResizeObserver below fires immediately when dimensions settle and
    // calls chart.resize(), which corrects the layout.  The old early-return
    // here exited *before* calling init(), so the chart was never created.
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

    // Auto-resize when container dimensions change.
    // Do NOT call scrollToRealTime() here — that would jump the user's view
    // position every time the window is resized, making candles appear to
    // desync from overlays.  scrollToRealTime() only belongs in the data effect
    // (after applyNewData) where it's intentional.
    const ro = new ResizeObserver(() => { chartRef.current?.resize(); });
    ro.observe(el);

    // Wheel zoom — CAPTURE PHASE trick to prevent double-zoom:
    //   KLineChart registers its handler on the canvas (a child of el).
    //   Normal (bubble-phase) listeners on el fire AFTER the canvas handler,
    //   so calling zoomAtCoordinate there zoomed the chart twice per tick.
    //   Using { capture: true } makes our handler fire BEFORE canvas handlers
    //   (capture phase travels window→el→canvas; bubble goes the other way).
    //   Then stopPropagation() stops the event from ever reaching the canvas,
    //   so KLineChart never sees it.  Result: exactly ONE zoom per scroll tick.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation(); // block KLineChart's canvas handler
      if (!chartRef.current) return;
      const rect = el.getBoundingClientRect();
      const scale = e.deltaY < 0 ? 1.1 : 0.9;
      try {
        chartRef.current.zoomAtCoordinate(scale, {
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
        });
      } catch (_) {}
    };
    el.addEventListener("wheel", onWheel, { passive: false, capture: true });

    return () => {
      el.removeEventListener("wheel", onWheel, { capture: true });
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
      // getIndicatorByPaneId returns an array; !![] is truthy even when empty,
      // so we must check length explicitly — otherwise VWAP is never created.
      const _vwapResult = chart.getIndicatorByPaneId("candle_pane", "VWAP");
      const hasVwap = Array.isArray(_vwapResult) ? _vwapResult.length > 0 : !!_vwapResult;
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
    try { chart.removeOverlay({ groupId: "edu" }); } catch (_) { /* no-op */ }

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

    // ── Educational chart drawings ─────────────────────────────────────────────
    // These help users understand WHAT is being drawn and WHY — training overlays
    // that are always present regardless of whether the bot has traded.
    //
    // 1) OR Zone shaded rect: semi-transparent band between OR High/Low over the
    //    first 30-minute window (9:30–10:00 AM ET = first 6 bars on 5Min).
    //    Shows users visually where the opening range formed.
    // 2) Key session time markers: dashed vertical lines at market open (9:30),
    //    end of OR window (10:00), midday (12:00), afternoon session (2:00 PM)
    //    and last hour (3:00 PM) — teaches time-of-day awareness.
    if (bars.length > 0 && showOR && orHigh != null && orLow != null) {
      // Locate key session timestamps from the bars data.
      // Bars use the user's local time string; extract hour/min from each bar.
      const SESSION_LABELS: Array<[number, number, string]> = [
        [9, 30,  "Market Open"],
        [10, 0,  "OR Close"],
        [12, 0,  "Midday"],
        [14, 0,  "Afternoon"],
        [15, 0,  "Final Hour"],
      ];
      let orStartTs: number | null  = null;
      let orEndTs:   number | null  = null;
      for (const [h, m, _label] of SESSION_LABELS) {
        const match = bars.find((b) => {
          const d = new Date(b.time);
          return d.getHours() === h && d.getMinutes() === m;
        });
        if (match) {
          const ts = new Date(match.time).getTime();
          if (h === 9  && m === 30) orStartTs = ts;
          if (h === 10 && m === 0)  orEndTs   = ts;
          // Vertical dashed time marker
          try {
            chart.createOverlay({
              name: "verticalStraightLine",
              groupId: "edu",
              lock: true,
              points: [{ timestamp: ts }],
              needDefaultYAxisFigure: false,
              styles: { line: { color: "#ffffff1a", size: 1, style: "dashed", dashedValue: [4, 3] } },
            });
          } catch (_) {}
        }
      }
      // OR Zone shaded rectangle — shows the opening range band visually
      if (orStartTs != null && orEndTs != null) {
        try {
          chart.createOverlay({
            name: "rect",
            groupId: "edu",
            lock: true,
            points: [
              { timestamp: orStartTs, value: orLow  },
              { timestamp: orEndTs,   value: orHigh },
            ],
            needDefaultYAxisFigure: false,
            styles: {
              polygon: { style: "fill", color: `${up}14` },
              line:    { color: `${up}30`, size: 1, style: "dashed", dashedValue: [4, 2] },
            },
          });
        } catch (_) {}
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

    // ── Bot annotation overlays (hline / zone) ───────────────────────────────
    // Clear previous annotation group then redraw from fresh poll data.
    // "marker" type is skipped here — KLineChart has no native candle marker API.
    // hline  → one horizontalStraightLine at ann.price
    // zone   → two horizontalStraightLines (top and bottom of the gap band)
    try { chart.removeOverlay({ groupId: "ann" }); } catch (_) { /* no-op */ }

    for (const ann of annotations) {
      try {
        if (ann.type === "hline" && ann.price != null) {
          chart.createOverlay({
            name: "horizontalStraightLine",
            groupId: "ann",
            lock: true,
            points: [{ value: ann.price }],
            styles: { line: { color: ann.color, size: 1, style: "dashed" as const, dashedValue: [4, 3] } },
            // DO NOT set needDefaultYAxisFigure: true on annotations — bot annotation
            // prices from other sessions can be far outside today's range, which forces
            // KLineChart to expand the Y-axis to include them (660–840 bloat bug).
            needDefaultYAxisFigure: false,
          });
        } else if (ann.type === "zone" && ann.price_low != null && ann.price_high != null) {
          // Top edge of zone
          chart.createOverlay({
            name: "horizontalStraightLine",
            groupId: "ann",
            lock: true,
            points: [{ value: ann.price_high }],
            styles: { line: { color: ann.color, size: 1, style: "dashed" as const, dashedValue: [4, 3] } },
            needDefaultYAxisFigure: false,
          });
          // Bottom edge of zone (same color, thinner)
          chart.createOverlay({
            name: "horizontalStraightLine",
            groupId: "ann",
            lock: true,
            points: [{ value: ann.price_low }],
            styles: { line: { color: ann.color, size: 1, style: "dashed" as const, dashedValue: [4, 3] } },
            needDefaultYAxisFigure: false,
          });
        }
      } catch (_) { /* skip if overlay type not available */ }
    }

  }, [bars, tf, showVwap, showVwapBands, showOR, orHigh, orLow, positionLevels, annotations]);

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
          title="Reset zoom to default view"
          onClick={() => {
            try {
              chartRef.current?.scrollToRealTime();
              // Re-apply natural bar spacing for the current TF so the chart
              // snaps back to the original zoom level, not a zoomed-out mess.
              const naturalCount: Record<string, number> = {
                "1Min": 240, "5Min": 100, "15Min": 50, "1Hour": 30,
              };
              const barsInView = naturalCount[tf] ?? 100;
              const containerW = containerRef.current?.clientWidth ?? 900;
              const barSpace   = Math.max(2, Math.min(30, (containerW - 70) / barsInView));
              chartRef.current?.setBarSpace(barSpace);
              // Force lastSpacingTf reset so next TF change re-applies spacing
              lastSpacingTf.current = "";
            } catch (_) {}
          }}
        >
          ⊙
        </button>
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

      {/* ── Chart legend strip — explains every colored element on the chart ── */}
      {(showVwap || showOR || (positionLevels && (positionLevels.entry ?? 0) > 0) || true) && (
        <div
          className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-1.5 text-[10px]"
          style={{ borderBottom: `1px solid ${border}`, background: dark ? "#0f131c" : "#f0f2f7", color: text }}
        >
          {/* VWAP */}
          {showVwap && (
            <span className="flex items-center gap-1">
              <span style={{ display:"inline-block", width:18, height:2, background:"#2962ff", borderRadius:1 }} />
              VWAP
            </span>
          )}
          {showVwap && showVwapBands && (
            <span className="flex items-center gap-1">
              <span style={{ display:"inline-block", width:18, height:2, background:"#2962ff66", borderRadius:1, borderTop:"1px dashed #2962ff88" }} />
              ±1σ Band
            </span>
          )}
          {/* OR levels */}
          {showOR && orHigh != null && (
            <span className="flex items-center gap-1">
              <span style={{ display:"inline-block", width:18, height:2, background:up, borderRadius:1 }} />
              OR High <span style={{ opacity:0.7 }}>({orHigh.toFixed(2)})</span>
            </span>
          )}
          {showOR && orLow != null && (
            <span className="flex items-center gap-1">
              <span style={{ display:"inline-block", width:18, height:2, background:dn, borderRadius:1 }} />
              OR Low <span style={{ opacity:0.7 }}>({orLow.toFixed(2)})</span>
            </span>
          )}
          {/* Position price lines */}
          {positionLevels && (positionLevels.entry ?? 0) > 0 && (
            <>
              <span className="flex items-center gap-1">
                <span style={{ display:"inline-block", width:18, height:2, background:"#eab308", borderRadius:1 }} />
                Entry
              </span>
              {(positionLevels.stop ?? 0) > 0 && (
                <span className="flex items-center gap-1">
                  <span style={{ display:"inline-block", width:18, height:2, background:dn, borderRadius:1, opacity:0.7 }} />
                  Stop
                </span>
              )}
              {(positionLevels.target ?? 0) > 0 && (
                <span className="flex items-center gap-1">
                  <span style={{ display:"inline-block", width:18, height:2, background:up, borderRadius:1, opacity:0.7 }} />
                  Target
                </span>
              )}
              {(positionLevels as any).trail > 0 && (
                <span className="flex items-center gap-1">
                  <span style={{ display:"inline-block", width:18, height:2, background:"#9333ea", borderRadius:1 }} />
                  Trail
                </span>
              )}
            </>
          )}
          {/* OR zone educational indicator */}
          {showOR && orHigh != null && orLow != null && (
            <span className="flex items-center gap-1">
              <span style={{ display:"inline-block", width:14, height:8,
                             background:`${up}14`, borderRadius:2,
                             border:`1px dashed ${up}55` }} />
              OR Zone <span style={{ opacity:0.6, fontSize:9 }}>(9:30–10:00 AM)</span>
            </span>
          )}
          {/* Bot scanning status / annotation legend */}
          {annotations.length === 0 ? (
            <span style={{ opacity:0.45, fontStyle:"italic", fontSize:9 }}>
              Bot scanning — strategy zones appear here when a setup fires
            </span>
          ) : (() => {
            // Deduplicate annotation labels so we don't show "FVG zone, FVG zone, FVG zone"
            const seen = new Set<string>();
            return annotations.filter(a => {
              const key = `${a.strategy}:${a.label}`;
              if (seen.has(key)) return false;
              seen.add(key);
              return true;
            }).slice(0, 5).map((ann) => (
              <span key={ann.id} className="flex items-center gap-1">
                <span style={{ display:"inline-block", width:14, height:2,
                               background:ann.color, borderRadius:1,
                               borderTop:`1px dashed ${ann.color}` }} />
                {ann.label}
              </span>
            ));
          })()}
          {/* Time key */}
          <span style={{ marginLeft:"auto", opacity:0.35, fontSize:9, whiteSpace:"nowrap" }}>
            ⊙ = Reset zoom
          </span>
        </div>
      )}

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
