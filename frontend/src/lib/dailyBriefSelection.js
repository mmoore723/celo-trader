/**
 * Pick the first Daily Brief ticker only after the watchlist and premarket
 * requests have both settled. Watchlist order wins because it reflects the
 * user's configured priorities; scanner-only names are fallback candidates.
 */
export function preferredDailyBriefTicker({
  selected,
  loading,
  pinnedTickers,
  premarketTickers,
  scannerTickers,
}) {
  if (loading) return selected;

  const available = [...new Set([
    ...pinnedTickers,
    ...premarketTickers,
    ...scannerTickers,
  ])];

  if (selected && available.includes(selected)) return selected;
  return available[0] ?? "";
}
