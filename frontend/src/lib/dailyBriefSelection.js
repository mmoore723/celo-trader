/**
 * Pick only from tickers that have a complete pre-market report.
 */
export function preferredDailyBriefTicker({
  selected,
  loading,
  premarketTickers,
}) {
  if (loading) return selected;
  const available = [...new Set(premarketTickers)];

  if (selected && available.includes(selected)) return selected;
  return available[0] ?? "";
}
