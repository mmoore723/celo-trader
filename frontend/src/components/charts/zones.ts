/**
 * zones.ts — shaded-region definitions: premium/discount split + killzones.
 *
 * Both computed entirely client-side from bars already on the chart — no new
 * backend data required.
 *
 * Premium/discount: split the recent range in half. Upper half = "premium"
 * (where SMC/ICT-style readers look to sell/short), lower half = "discount"
 * (where they look to buy/long). This is ONE framework for reading a range,
 * not the only valid one — presented on the chart as a labeled teaching
 * overlay, not as an objective buy/sell signal.
 *
 * Killzones: fixed time-of-day windows. Celo Trader only trades regular US
 * session hours (9:30-16:00 ET), so the two windows that actually matter here
 * are the opening range (already shaded elsewhere as "OR Zone") and the last
 * hour ("power hour"), where volume/volatility reliably pick back up. These
 * are a documented design choice, not a claim about universal market
 * behavior.
 */
import type { Bar } from "../../lib/api";

export interface RangeZone {
  high: number;
  low: number;
  mid: number;
}

/** Premium/discount split over the last `lookback` bars (default: full visible set). */
export function premiumDiscountRange(bars: Bar[], lookback?: number): RangeZone | null {
  if (bars.length === 0) return null;
  const slice = lookback ? bars.slice(-lookback) : bars;
  const high = Math.max(...slice.map((b) => b.high));
  const low = Math.min(...slice.map((b) => b.low));
  if (!(high > low)) return null;
  return { high, low, mid: (high + low) / 2 };
}

export interface KillzoneWindow {
  key: string;
  label: string;
  startHour: number;   // ET, 24h
  startMin: number;
  endHour: number;
  endMin: number;
}

// ET session windows. The bot is regular-hours-only, so pre/post-market
// "London"/"Asia" killzones from the wider ICT framework don't apply here —
// these two are the ones with a real, checkable effect on this bot's own
// intraday volume/volatility.
export const KILLZONES: KillzoneWindow[] = [
  { key: "open",  label: "Opening Window",  startHour: 9,  startMin: 30, endHour: 10, endMin: 0 },
  { key: "power", label: "Power Hour",      startHour: 15, startMin: 0,  endHour: 16, endMin: 0 },
];

/** Epoch-ms [start, end) for a killzone window on the same calendar day as `sampleIso`. */
export function killzoneRangeForDay(kz: KillzoneWindow, sampleIso: string): { start: number; end: number } {
  const d = new Date(sampleIso);
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), kz.startHour, kz.startMin, 0, 0).getTime();
  const end = new Date(d.getFullYear(), d.getMonth(), d.getDate(), kz.endHour, kz.endMin, 0, 0).getTime();
  return { start, end };
}

/** All killzone windows that fall within the loaded bar range, one per calendar day present. */
export function killzoneRangesForBars(bars: Bar[]): { key: string; label: string; start: number; end: number }[] {
  if (bars.length === 0) return [];
  const days = new Set<string>();
  for (const b of bars) days.add(b.time.slice(0, 10));

  const out: { key: string; label: string; start: number; end: number }[] = [];
  for (const day of days) {
    for (const kz of KILLZONES) {
      const { start, end } = killzoneRangeForDay(kz, `${day}T00:00:00`);
      out.push({ key: `${kz.key}_${day}`, label: kz.label, start, end });
    }
  }
  return out;
}
