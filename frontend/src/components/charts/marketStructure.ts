/** Chart-only structure, not an execution policy. Fixed five-bar pivots.
 * Labels use the following bar: confirmation candle has closed, no backdating.
 * This is candle-based confirmation, not proof of bot receipt time.
 */
import type { Bar } from "../../lib/api";
export const SWING_CONFIRMATION_BARS = 5;
export interface SwingPoint {
  idx: number; confirmedIdx: number; time: string; pivotTime: string; price: number;
  kind: "SH" | "SL"; label: "SH" | "SL" | "HH" | "LH" | "HL" | "LL";
}
export function detectSwings(bars: Bar[], lookback = SWING_CONFIRMATION_BARS): SwingPoint[] {
  if (!Number.isInteger(lookback) || lookback < 1) return [];
  const out: SwingPoint[] = [];
  let lastHigh: number | undefined, lastLow: number | undefined;
  for (let i = lookback; i + lookback + 1 < bars.length; i++) {
    const b = bars[i];
    const neighbors = bars.slice(i-lookback, i).concat(bars.slice(i+1, i+lookback+1));
    const confirmedIdx = i + lookback + 1;
    const base = { idx:i, confirmedIdx, time:bars[confirmedIdx].time, pivotTime:b.time };
    if (neighbors.every(n => b.high > n.high)) {
      out.push({ ...base, price:b.high, kind:"SH", label:lastHigh == null ? "SH" : b.high > lastHigh ? "HH" : "LH" });
      lastHigh = b.high;
    }
    if (neighbors.every(n => b.low < n.low)) {
      out.push({ ...base, price:b.low, kind:"SL", label:lastLow == null ? "SL" : b.low > lastLow ? "HL" : "LL" });
      lastLow = b.low;
    }
  }
  return out;
}
export interface StructureLabel {
  time: string; text: string; direction: "up" | "down" | "neutral"; event: boolean;
}
/** A break is a completed close through an already confirmed pivot.
 * HH alone is not CHoCH. Only the opposite break changes directional state.
 */
export function structureLabels(bars: Bar[], includeBreaks = true): StructureLabel[] {
  const swings = detectSwings(bars);
  const out: StructureLabel[] = swings.map(s => ({ time:s.time,
    text:`${s.label} confirmed`, event:false,
    direction:s.label === "HH" || s.label === "HL" ? "up" : s.label === "LH" || s.label === "LL" ? "down" : "neutral" }));
  if (!includeBreaks) return out;
  let high: SwingPoint | undefined, low: SwingPoint | undefined;
  let brokenHigh: number | undefined, brokenLow: number | undefined;
  let trend: "up" | "down" | undefined;
  let si = 0;
  for (let i = 1; i < bars.length; i++) {
    // Levels must be known before the candle being tested began.
    while (si < swings.length && swings[si].confirmedIdx <= i-1) {
      const s = swings[si++];
      if (s.kind === "SH") high=s; else low=s;
    }
    const close = bars[i-1].close;
    let direction: "up" | "down" | undefined;
    if (high && high.idx !== brokenHigh && close > high.price) {
      direction="up"; brokenHigh=high.idx;
    } else if (low && low.idx !== brokenLow && close < low.price) {
      direction="down"; brokenLow=low.idx;
    }
    if (!direction) continue;
    const kind = trend == null ? "break" : trend === direction ? "BOS" : "CHoCH";
    out.push({ time:bars[i].time, text:`${direction === "up" ? "Bullish" : "Bearish"} ${kind}`, direction, event:true });
    trend=direction;
  }
  return out.sort((a,b) => a.time.localeCompare(b.time));
}

/** Display only: keep confirmed structure readable at full-session scale. */
export function compactStructureLabels(bars: Bar[], labels: StructureLabel[]): StructureLabel[] {
  const spacing = Math.max(8, Math.ceil(bars.length / 8));
  const selected: StructureLabel[] = [];
  const indices = new Map(bars.map((bar, i) => [bar.time, i]));
  // Keep the latest context, without piling adjacent labels on each other.
  for (const label of [...labels].reverse()) {
    const index = indices.get(label.time);
    if (index == null || selected.some(other => Math.abs(index - (indices.get(other.time) ?? index)) < spacing)) continue;
    const text = label.text.replace(" confirmed", "").replace("Bullish ", "").replace("Bearish ", "");
    selected.push({ ...label, text: label.event ? `${text === "break" ? "Break" : text} ${label.direction === "up" ? "↑" : "↓"}` : text });
    if (selected.length === 6) break;
  }
  return selected.reverse();
}
