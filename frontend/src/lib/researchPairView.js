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

export function researchPairVisible(pair, filter) {
  if (filter === "all") return true;
  if (filter === "attention") return ["price_data", "unstable", "early_loss", "entry", "exit", "contract_exit"].includes(pair.diagnosis);
  if (filter === "passing") return ["working", "promising"].includes(pair.status);
  return pair.setups > 0 || pair.option_results > 0;
}

export function sortResearchPairs(rows) {
  return [...rows].sort((a, b) =>
    (STATUS_RANK[a.pair.status] ?? 99) - (STATUS_RANK[b.pair.status] ?? 99)
    || b.pair.option_results - a.pair.option_results
    || a.strategy.display_name.localeCompare(b.strategy.display_name)
    || a.pair.ticker.localeCompare(b.pair.ticker)
  );
}
