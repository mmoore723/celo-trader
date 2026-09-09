const STATUS_RANK = {
  working: 0,
  promising: 1,
  losing_so_far: 2,
  needs_tuning: 3,
  not_working: 4,
  collecting: 5,
  no_setups: 6,
};

const ACTION_LABELS = {
  ready: "Ready for review",
  more_data: "Keep collecting",
  no_setups: "No setup yet",
  price_data: "Fix price data",
  contract_selection: "No option matched",
  unstable: "Changed over time",
  early_loss: "Losing — review",
  entry: "Fix the entry",
  exit: "Test the exit",
  contract_exit: "Test option + exit",
};

export function researchActionLabel(diagnosis) {
  return ACTION_LABELS[diagnosis] ?? "Review this pair";
}

export function profitFactorText(value) {
  if (value === "infinite") return "∞";
  return typeof value === "number" ? value.toFixed(2) : "—";
}

/** Human-readable live PF. A win-only sample has no gross loss denominator. */
export function researchProfitFactorText(value, results) {
  if (!results) return "—";
  if (value === "infinite") return "No losses yet";
  return typeof value === "number" ? value.toFixed(2) : "—";
}

export function numericProfitFactor(value) {
  if (value === "infinite") return Number.POSITIVE_INFINITY;
  return typeof value === "number" ? value : Number.NaN;
}

export function researchPairVisible(pair, filter) {
  if (filter === "all") return true;
  if (filter === "results") return pair.option_results > 0;
  if (filter === "no_option") return pair.option_results === 0 && pair.setups > 0;
  if (filter === "no_setup") return pair.setups === 0;
  if (filter === "attention") return ["price_data", "contract_selection", "unstable", "early_loss", "entry", "exit", "contract_exit"].includes(pair.diagnosis)
    || (pair.diagnosis === "no_setups" && pair.market_days >= 20);
  if (filter === "passing") return pair.option_results > 0 && numericProfitFactor(pair.profit_factor) >= 1.5;
  return pair.option_results > 0;
}

export function sortResearchPairs(rows) {
  return [...rows].sort((a, b) =>
    (STATUS_RANK[a.pair.status] ?? 99) - (STATUS_RANK[b.pair.status] ?? 99)
    || b.pair.option_results - a.pair.option_results
    || a.strategy.display_name.localeCompare(b.strategy.display_name)
    || a.pair.ticker.localeCompare(b.pair.ticker)
  );
}
