import type { Bar, OpeningRange } from "./api";

export function openingRangeForBars(
  bars: Bar[],
  openingRange: OpeningRange | undefined,
  enabled?: boolean,
): { high?: number; low?: number };
