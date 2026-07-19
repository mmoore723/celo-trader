/**
 * executionGrade.ts — "how strong was this candle/move" grading.
 *
 * Deliberately built ONLY from fields already on the `Bar` type the backend
 * sends (open/high/low/close/volume/rvol/atr) — no new backend endpoint, no
 * invented numbers. Two real, standard concepts:
 *
 *   - Body/wick ratio: how much of the candle's range is real body (conviction)
 *     vs wick (rejection). bodyRatio = |close-open| / (high-low).
 *   - Displacement: how large this bar's range is relative to its own recent
 *     volatility (ATR). A bar with range >> ATR is a "displacement" bar —
 *     the kind of strong, fast move that confirms a real move is happening.
 *
 * These combine into a simple three-level grade so a beginner sees "Strong /
 * Moderate / Weak" instead of raw ratios. This is a teaching overlay, not a
 * trading signal — it never feeds back into `trading/entry.py` or any live
 * decision; it only annotates a bar or trade entry that already happened.
 */
import type { Bar } from "../../lib/api";

export type Grade = "strong" | "moderate" | "weak";

export interface ExecutionGrade {
  grade: Grade;
  bodyRatio: number;       // 0-1
  displacement: number;    // bar range / ATR (1.0 = "normal" bar for this ticker)
  rvol: number | null;
  label: string;           // short human-readable summary
}

export function gradeBar(bar: Bar): ExecutionGrade | null {
  const range = bar.high - bar.low;
  if (range <= 0) return null;

  const bodyRatio = Math.min(1, Math.abs(bar.close - bar.open) / range);
  const displacement = bar.atr && bar.atr > 0 ? range / bar.atr : 1;
  const rvol = bar.rvol ?? null;

  // Simple, explainable point system — not a black box.
  let points = 0;
  if (bodyRatio >= 0.6) points += 1;       // mostly body, little rejection
  if (displacement >= 1.3) points += 1;    // bigger range than usual for this ticker
  if (rvol != null && rvol >= 1.5) points += 1;  // above-average participation

  const grade: Grade = points >= 2 ? "strong" : points === 1 ? "moderate" : "weak";

  const parts: string[] = [
    `${Math.round(bodyRatio * 100)}% body`,
    `${displacement.toFixed(1)}x ATR range`,
  ];
  if (rvol != null) parts.push(`${rvol.toFixed(1)}x volume`);

  return { grade, bodyRatio, displacement, rvol, label: parts.join(" · ") };
}
