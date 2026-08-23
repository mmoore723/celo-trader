/**
 * Return opening-range prices only when they belong to the same completed
 * trading session as the candles being displayed. This prevents stale levels
 * from stretching the live chart's price scale.
 */
export function openingRangeForBars(bars, openingRange, enabled = true) {
  if (!enabled || bars.length === 0 || !openingRange) return {};

  const chartSession = String(bars[bars.length - 1]?.time ?? "").slice(0, 10);
  const rangeSession = String(openingRange.time ?? "").slice(0, 10);
  const high = Number(openingRange.high ?? 0);
  const low = Number(openingRange.low ?? 0);
  const complete = Number(openingRange.bars ?? 0) >= 3;

  if (
    chartSession === ""
    || rangeSession !== chartSession
    || !complete
    || !Number.isFinite(high)
    || !Number.isFinite(low)
    || high <= low
  ) return {};

  return { high, low };
}
