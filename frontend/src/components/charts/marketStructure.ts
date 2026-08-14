/**
 * marketStructure.ts — swing-point detection + trend-structure classification.
 *
 * Single source of truth: this used to be hand-duplicated (same algorithm,
 * copy-pasted) between TradingChart.tsx and KChart.tsx. Both old files are
 * being retired in favor of one engine that imports this once.
 *
 * Two layers:
 *   1. detectSwings()      — raw pivot-high/pivot-low detection + HH/HL/LH/LL
 *                            labeling from consecutive same-kind pivots
 *                            (unchanged algorithm from the old chart files).
 *   2. classifyStructure() — NEW: walks the swing sequence and tags the first
 *      swing that breaks the prevailing trend as CHoCH (Change of Character),
 *      and any swing that *confirms* the new trend afterward as BOS (Break
 *      of Structure). This is the same distinction ICT/SMC-style market-
 *      structure reading uses. It is a client-side classification only — the
 *      this is a purely descriptive chart overlay for teaching, not a
 *      production strategy signal.
 */
import type { Bar } from "../../lib/api";

export interface SwingPoint {
  idx: number;
  time: string;     // ISO — caller converts to whatever Time type it needs
  price: number;
  kind: "SH" | "SL";
  label: "SH" | "SL" | "HH" | "LH" | "HL" | "LL";
}

export interface StructureEvent extends SwingPoint {
  /** "bos" = confirms the current trend direction continuing.
   *  "choch" = first swing that broke the prior trend — a heads-up, not a signal. */
  structure: "bos" | "choch" | null;
  trend: "up" | "down" | null;
}

export function detectSwings(bars: Bar[], lookback = 3): SwingPoint[] {
  const rawHighs: { idx: number; price: number }[] = [];
  const rawLows: { idx: number; price: number }[] = [];

  for (let i = lookback; i < bars.length - lookback; i++) {
    const b = bars[i];
    let isHigh = true, isLow = true;
    for (let j = i - lookback; j <= i + lookback; j++) {
      if (j === i) continue;
      if (bars[j].high >= b.high) isHigh = false;
      if (bars[j].low <= b.low) isLow = false;
    }
    if (isHigh) rawHighs.push({ idx: i, price: b.high });
    if (isLow) rawLows.push({ idx: i, price: b.low });
  }

  const out: SwingPoint[] = [];

  let prevHighPrice: number | null = null;
  for (const h of rawHighs) {
    const label: SwingPoint["label"] =
      prevHighPrice === null ? "SH" : h.price > prevHighPrice ? "HH" : "LH";
    prevHighPrice = h.price;
    out.push({ idx: h.idx, time: bars[h.idx].time, price: h.price, kind: "SH", label });
  }

  let prevLowPrice: number | null = null;
  for (const l of rawLows) {
    const label: SwingPoint["label"] =
      prevLowPrice === null ? "SL" : l.price > prevLowPrice ? "HL" : "LL";
    prevLowPrice = l.price;
    out.push({ idx: l.idx, time: bars[l.idx].time, price: l.price, kind: "SL", label });
  }

  out.sort((a, b) => a.idx - b.idx);
  return out;
}

/**
 * Walk a swing sequence and tag BOS / CHoCH.
 *
 * Rule (deliberately simple and explainable, not a proprietary indicator):
 *   - Track a running "trend" state: starts null (undetermined) until we see
 *     two consecutive same-direction swings (HH followed by HL, or LH
 *     followed by LL) — that establishes "up" or "down".
 *   - Once a trend is established, any swing that CONTINUES it (another HH
 *     or HL while up; another LH or LL while down) is tagged "bos".
 *   - The first swing that CONTRADICTS the established trend (an LH or LL
 *     appearing while trend="up"; an HH or HL appearing while trend="down")
 *     is tagged "choch" and flips the trend state.
 *   - SH/SL (first-ever pivot, no prior comparison) are untagged (null).
 */
export function classifyStructure(swings: SwingPoint[]): StructureEvent[] {
  const out: StructureEvent[] = [];
  let trend: "up" | "down" | null = null;

  for (const sw of swings) {
    let structure: StructureEvent["structure"] = null;
    const bullishSwing = sw.label === "HH" || sw.label === "HL";
    const bearishSwing = sw.label === "LH" || sw.label === "LL";

    if (bullishSwing || bearishSwing) {
      const swingTrend: "up" | "down" = bullishSwing ? "up" : "down";
      if (trend === null) {
        // First directional swing just seeds the trend — nothing to compare
        // against yet, so it's neither a continuation nor a reversal.
        trend = swingTrend;
      } else if (swingTrend === trend) {
        structure = "bos";
      } else {
        structure = "choch";
        trend = swingTrend;
      }
    }

    out.push({ ...sw, structure, trend });
  }

  return out;
}
