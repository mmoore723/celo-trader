/**
 * TradeChart.tsx — the one chart component. Replaces TradingChart.tsx (old
 * lightweight-charts version) and KChart.tsx (old klinecharts version) with
 * a single engine used on Live Trading, Journal, and Daily Brief alike.
 *
 * Replay is handled here via `revealCount` (how many bars to actually show)
 * rather than a masking overlay: RSI/MACD are computed once from the full
 * `bars` array and then sliced to the same length as the candles on every
 * render, so they can never fall out of step with each other — see
 * chartCore.ts's header comment for why this is lower-risk than the old
 * mask-overlay approach.
 */
import { useEffect, useRef, useState } from "react";
import type { Bar, Trade, ChartAnnotation } from "../../lib/api";
import type { SimulationOverlay, ReplayTrade } from "../../lib/chart_types";
import type { PositionLevels } from "./chartTypes";
import { useThemeStore } from "../../store/theme";
import { getPalette } from "./palette";
import { useChartCore } from "./chartCore";
import { OverlayManager } from "./chartOverlays";

export type { PositionLevels };

export interface TradeChartProps {
  bars: Bar[];
  trades?: Trade[];
  annotations?: ChartAnnotation[];
  showVwap?: boolean;
  showVwapBands?: boolean;
  showOR?: boolean;
  showSwings?: boolean;
  showStructure?: boolean;
  showPremiumDiscount?: boolean;
  showKillzones?: boolean;
  showExecutionGrade?: boolean;
  showRsi?: boolean;
  showMacd?: boolean;
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  simulationOverlay?: SimulationOverlay;
  replayTrade?: ReplayTrade;
  height?: number;
  ticker?: string;
  showPositionCard?: boolean;
  currentOptionPrice?: number | null;
  /** How many of `bars` to actually display — undefined/omitted = all of them (live/full view). */
  revealCount?: number;
  /** Left edge of the visible window (bar index) — undefined/omitted = 0 (from the start). */
  revealStart?: number;
  /** Refit only when this chart context changes, never on routine data polls. */
  viewportKey?: string;
}

export function TradeChart({
  bars, trades = [], annotations = [],
  showVwap = true, showVwapBands = true, showOR = true, showSwings = true,
  showStructure = true, showPremiumDiscount = false, showKillzones = false, showExecutionGrade = true,
  showRsi = true, showMacd = true,
  orHigh, orLow, positionLevels, simulationOverlay, replayTrade,
  height = 420, ticker, revealCount, revealStart, viewportKey,
  showPositionCard = true, currentOptionPrice = null,
}: TradeChartProps) {
  const mainRef = useRef<HTMLDivElement>(null);
  const rsiRef = useRef<HTMLDivElement>(null);
  const macdRef = useRef<HTMLDivElement>(null);
  const overlayMgr = useRef<OverlayManager | null>(null);

  const { theme } = useThemeStore();
  const palette = getPalette(theme === "dark");

  const { refs, setBars } = useChartCore(mainRef, rsiRef, macdRef, palette, { height, showRsi, showMacd, viewportKey });

  // Visible slice for replay — bounded on BOTH sides. `revealStart` (e.g.
  // entry-15 from a boomerang jump) keeps prior days/sessions out of view;
  // without it, "reveal up to revealCount" alone still includes everything
  // from bar 0, which is what caused a trade near the tail of a multi-day
  // fetch window to render the whole week instead of just its own session.
  // Trades/annotations are filtered to the same cutoff so "don't spoil the
  // outcome" holds for markers too.
  const start = revealStart ?? 0;
  const visibleBars = revealCount != null ? bars.slice(start, Math.max(start + 1, revealCount)) : bars;
  const cutoffTime = revealCount != null ? visibleBars[visibleBars.length - 1]?.time : undefined;
  const visibleTrades = cutoffTime ? trades.filter((t) => t.entry_time && t.entry_time <= cutoffTime) : trades;
  const visibleAnnotations = cutoffTime ? annotations.filter((a) => a.ts <= cutoffTime) : annotations;

  // Create the OverlayManager once the chart/candle series exist.
  useEffect(() => {
    if (!refs.current.chart || !refs.current.candle) return;
    overlayMgr.current = new OverlayManager(refs.current.chart, refs.current.candle, palette);
    return () => { overlayMgr.current?.destroy(); overlayMgr.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refs.current.chart]);

  useEffect(() => {
    setBars(visibleBars);
    overlayMgr.current?.setVwap(visibleBars, showVwap, showVwapBands);
    overlayMgr.current?.apply({
      bars: visibleBars, trades: visibleTrades, annotations: visibleAnnotations,
      showVwap, showSwings, showStructure, showPremiumDiscount, showKillzones, showExecutionGrade,
      orHigh: showOR ? orHigh : undefined,
      orLow: showOR ? orLow : undefined,
      positionLevels, simulationOverlay, replayTrade,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    bars, trades, annotations, revealCount, revealStart, showVwap, showVwapBands, showOR, showSwings,
    showStructure, showPremiumDiscount, showKillzones, showExecutionGrade,
    orHigh, orLow, positionLevels, simulationOverlay, replayTrade,
  ]);

  const [cardHovered, setCardHovered] = useState(false);
  const pl = positionLevels;

  return (
    <div className="flex flex-col w-full" onWheel={(e) => e.stopPropagation()}>
      <div className="relative w-full" style={{ height }}>
        <div className="absolute top-2 left-3 z-10" style={{ pointerEvents: "none" }}>
          {ticker && <span className="text-sm font-mono font-bold" style={{ color: "var(--ink)" }}>{ticker}</span>}
        </div>

        {showPositionCard && pl?.entry && (() => {
          const isLong = (pl.direction ?? "long") === "long";
          const unrealPnl = currentOptionPrice != null && pl.contracts ? (currentOptionPrice - pl.entry!) * pl.contracts * 100 : null;
          const unrealPct = currentOptionPrice != null ? (currentOptionPrice - pl.entry!) / pl.entry! * 100 : null;
          const pnlColor = unrealPnl == null ? "var(--ink-muted)" : unrealPnl >= 0 ? palette.target : palette.stop;
          return (
            <div
              onMouseEnter={() => setCardHovered(true)}
              onMouseLeave={() => setCardHovered(false)}
              className="absolute z-20"
              style={{ top: 36, left: 8, fontFamily: "JetBrains Mono, monospace", fontSize: 11, minWidth: 130 }}
            >
              <div style={{
                display: "inline-flex", alignItems: "center", gap: 6, borderRadius: 4, padding: "3px 8px",
                background: isLong ? "rgba(63,185,80,0.18)" : "rgba(248,81,73,0.18)",
                color: isLong ? palette.target : palette.stop,
                border: `1px solid ${isLong ? palette.target : palette.stop}`,
                fontWeight: 700, fontSize: 10,
              }}>
                {isLong ? "▲ LONG" : "▼ SHORT"}{pl.contracts ? ` · ${pl.contracts}×` : ""}
              </div>
              {unrealPnl != null && (
                <div style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 2, borderRadius: 4, padding: "2px 8px", background: unrealPnl >= 0 ? "rgba(63,185,80,0.12)" : "rgba(248,81,73,0.12)", border: `1px solid ${pnlColor}44` }}>
                  <span style={{ color: pnlColor, fontWeight: 700, fontSize: 12 }}>{unrealPnl >= 0 ? "+" : ""}${unrealPnl.toFixed(2)}</span>
                  {unrealPct != null && <span style={{ color: pnlColor, opacity: 0.75, fontSize: 9 }}>({unrealPct >= 0 ? "+" : ""}{unrealPct.toFixed(1)}%)</span>}
                </div>
              )}
              {cardHovered && pl.stop && <div style={{ fontSize: 10, color: palette.stop, marginTop: 2 }}>Stop {pl.stop.toFixed(2)}</div>}
              {cardHovered && pl.target && <div style={{ fontSize: 10, color: palette.target, marginTop: 2 }}>Target {pl.target.toFixed(2)}</div>}
            </div>
          );
        })()}

        {simulationOverlay && (
          <div className="absolute z-30" style={{ top: 8, left: "50%", transform: "translateX(-50%)", background: "rgba(245,158,11,0.15)", border: "1px solid #f59e0b", borderRadius: 6, padding: "3px 14px", fontSize: 10, fontWeight: 700, color: "#f59e0b" }}>
            SIMULATION — {simulationOverlay.direction.toUpperCase()} · Grade {simulationOverlay.grade}
          </div>
        )}
        {replayTrade && (
          <div className="absolute z-30" style={{ top: 8, left: "50%", transform: "translateX(-50%)", background: "rgba(167,139,250,0.15)", border: "1px solid #a78bfa", borderRadius: 6, padding: "3px 14px", fontSize: 10, fontWeight: 700, color: "#a78bfa" }}>
            REPLAY — Entry ${replayTrade.entry_option_px.toFixed(2)}
          </div>
        )}

        {/* MTF alignment heat strip — did 1m/5m/15m/1h trend agree with this
            entry's direction? Teaching overlay only, from Trade.mtf_bias
            (see trading/mtf_features.py::compute_mtf_alignment()). Absent
            (undefined) for trades recorded before this feature existed, or
            if the best-effort lookup failed at entry — shows nothing rather
            than a misleading "neutral" row in that case. */}
        {replayTrade?.mtfBias && (
          <div className="absolute z-20" style={{ top: 8, right: 8, display: "flex", gap: 3, pointerEvents: "none" }}>
            {(["1Min", "5Min", "15Min", "1Hour"] as const).map((tf) => {
              const bias = replayTrade.mtfBias?.[tf];
              if (!bias) return null;
              const color = bias === "with" ? palette.up : bias === "against" ? palette.down : palette.text;
              const bg = bias === "with" ? "rgba(38,166,154,0.15)" : bias === "against" ? "rgba(239,83,80,0.15)" : "rgba(148,163,184,0.15)";
              return (
                <div key={tf} title={`${tf}: ${bias}`} style={{ fontSize: 9, fontWeight: 700, padding: "2px 5px", borderRadius: 4, background: bg, color, border: `1px solid ${color}55` }}>
                  {tf.replace("Min", "m").replace("Hour", "h")}
                </div>
              );
            })}
          </div>
        )}

        <div ref={mainRef} className="w-full h-full" />
      </div>

      {showRsi && (
        <div className="relative w-full" style={{ height: 100, borderTop: `1px solid ${palette.border}` }}>
          <div className="absolute top-1 left-3 z-10 text-[10px] font-mono" style={{ color: palette.rsi, pointerEvents: "none" }}>RSI(14)</div>
          <div ref={rsiRef} className="w-full h-full" />
        </div>
      )}
      {showMacd && (
        <div className="relative w-full" style={{ height: 120, borderTop: `1px solid ${palette.border}` }}>
          <div className="absolute top-1 left-3 z-10 text-[10px] font-mono" style={{ color: palette.macdLine, pointerEvents: "none" }}>MACD(12,26,9)</div>
          <div ref={macdRef} className="w-full h-full" />
        </div>
      )}
    </div>
  );
}
