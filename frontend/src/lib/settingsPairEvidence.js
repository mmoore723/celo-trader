export function settingsPairEvidenceRows(pairs, tradingTickers) {
  const enabled = tradingTickers === undefined ? null : new Set(tradingTickers);
  return pairs.map(pair => ({ pair, trading: enabled ? enabled.has(pair.ticker) : Boolean(pair.tradable) }))
    .filter(row => row.pair.option_results > 0 || row.trading)
    .sort((a, b) => Number(b.trading) - Number(a.trading)
      || a.pair.ticker.localeCompare(b.pair.ticker));
}
