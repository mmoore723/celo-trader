export function closedTradeText(pair) {
  if (!pair.completed_trades) return `${pair.ticker} · No closed trades for v${pair.version}`;
  const pf = pair.profit_factor === "infinite" ? "No losses yet"
    : typeof pair.profit_factor === "number" ? `PF ${pair.profit_factor.toFixed(2)}` : "PF —";
  const pnl = typeof pair.realized_pnl === "number"
    ? `${pair.realized_pnl < 0 ? "−" : "+"}$${Math.abs(pair.realized_pnl).toFixed(2)}` : "P&L unavailable";
  return `${pair.ticker} · ${pf} · ${pair.completed_trades} closed · ${pnl}`;
}
