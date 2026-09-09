import type { Bar } from "../../lib/api";

export const POSITION_WINDOW_MINUTES = 20;

/** Return a one-minute position window with complete candles on both sides. */
export function tradeWindowBounds(
  bars: Bar[], entryTime: string, exitTime?: string, paddingMinutes = POSITION_WINDOW_MINUTES,
) {
  if (bars.length === 0) return { startIndex: 0, endIndex: 0 };
  const entryMs = Date.parse(entryTime);
  if (!Number.isFinite(entryMs)) return { startIndex: 0, endIndex: bars.length };

  const minuteMs = 60_000;
  const entryMinute = Math.floor(entryMs / minuteMs) * minuteMs;
  const startAt = entryMinute - paddingMinutes * minuteMs;
  const foundStart = bars.findIndex((bar) => Date.parse(bar.time) >= startAt);
  const startIndex = foundStart < 0 ? 0 : foundStart;

  const exitMs = exitTime ? Date.parse(exitTime) : Number.NaN;
  if (!Number.isFinite(exitMs)) return { startIndex, endIndex: bars.length };
  const exitMinute = Math.floor(exitMs / minuteMs) * minuteMs;
  const endAt = exitMinute + paddingMinutes * minuteMs;
  const foundEnd = bars.findIndex((bar) => Date.parse(bar.time) > endAt);
  const endIndex = foundEnd < 0 ? bars.length : foundEnd;
  return { startIndex, endIndex: Math.max(startIndex + 1, endIndex) };
}
