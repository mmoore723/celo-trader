/** Shared scanner lifecycle rules used by the full audit page and live feed. */
export function opportunityLifecycle(entry) {
  if (entry?.lifecycle) return String(entry.lifecycle);
  if (entry?.outcome === "entered") return "entered";
  if (entry?.outcome === "blocked") return "stopped";
  if (entry?.outcome === "observed_only") return "research";
  if (entry?.plan_status === "contract_selected") return "ready";
  if (entry?.plan_status === "contract_preview") return "pricing";
  return "watching";
}

export function isOperationalOpportunity(entry) {
  return opportunityLifecycle(entry) !== "research";
}

export function lifecycleCopy(entry) {
  const lifecycle = opportunityLifecycle(entry);
  if (lifecycle === "entered" && (entry?.trade?.exit_time || String(entry?.trade?.status).toLowerCase() === "closed"))
    return { title: "Trade Closed", badge: "CLOSED", detail: "This is a past entry. The position has closed." };
  if (lifecycle === "entered" && String(entry?.trade?.status).toLowerCase() === "open")
    return { title: "Open Position", badge: "OPEN", detail: "The linked trade is still open." };
  const copies = {
    watching: { title: "Setup Developing", badge: "WATCHING", detail: "The chart pattern is not complete yet." },
    pricing: { title: "Checking Contract", badge: "PRICING", detail: "The setup reached option liquidity and affordability checks." },
    ready: { title: "Trade Ready", badge: "READY", detail: "A contract was selected; the bot is waiting for the recorded entry trigger." },
    stopped: { title: "Setup Stopped", badge: "STOPPED", detail: "A recorded rule prevented this setup from entering." },
    entered: { title: "Past Entry", badge: "ENTERED", detail: "An entry was recorded. This does not mean the position is still open." },
    research: { title: "Research Observation", badge: "RESEARCH", detail: "This observation was never authorized to place an order." },
  };
  return copies[lifecycle] ?? copies.watching;
}

export function opportunityDecisionTitle(entry) {
  if (entry?.outcome === "entered") return "Trade entered";
  if (entry?.reason_code === "entry_price_not_reached") return "Order sent · not filled";
  if (entry?.reason_code === "stale_entry_quote") return "Skipped: option price was delayed";
  if (entry?.reason_code === "spy_trend_level_too_close") return "Skipped: next price wall was too close";
  const lifecycle = opportunityLifecycle(entry);
  return {
    stopped: "Skipped by a safety rule",
    ready: "Ready for entry",
    pricing: "Option preview recorded",
    watching: "Setup developing",
  }[lifecycle] || "Setup reviewed";
}

export function opportunityReason(entry) {
  if (!entry?.reason_code && !entry?.reason_detail && entry?.entry_plan?.trigger === "raw strategy setup detected")
    return "Setup and option preview recorded. No final entry decision was recorded for this setup.";
  const known = {
    entry_price_not_reached: "The order was sent, but the option never traded inside the bot's approved price range.",
    spy_afternoon_fvg_slot_reserved: "The bot saved this time slot for the higher-priority afternoon strategy.",
    daily_trade_limit_reached: "The account had already reached its trade limit for the day.",
    max_open_positions: "The account already had the maximum number of open positions.",
    cooldown_active: "The bot was waiting through its required cooldown after an earlier setup.",
  };
  if (entry?.reason_code === "stale_entry_quote") {
    const match = String(entry?.reason_detail || "").match(/was\s+([\d.]+)s\s+old/i);
    const observedAge = match ? `${match[1]} seconds old` : "missing a current timestamp";
    return `The exact Tradier option price was ${observedAge}. The bot requires a quote no more than 120 seconds old, so no order was sent. This usually means the delayed sandbox price feed is being used.`;
  }
  return (
    (entry?.reason_code && known[entry.reason_code])
    || entry?.reason_detail
    || entry?.entry_plan?.trigger
    || lifecycleCopy(entry).detail
  );
}

export function dedupeLatestEpisodes(entries, limit = 3) {
  const seen = new Set();
  const result = [];
  for (const entry of entries ?? []) {
    if (!isOperationalOpportunity(entry)) continue;
    const key = entry.episode_id || `${entry.ticker}|${entry.strategy_id}|${entry.direction}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(entry);
    if (result.length >= limit) break;
  }
  return result;
}

export function collapseOpportunityEpisodes(entries) {
  const rank = { research: 0, watching: 1, pricing: 2, ready: 3, stopped: 4, entered: 5 };
  const selected = new Map();
  for (const entry of entries ?? []) {
    const key = entry.episode_id || entry.id;
    const prior = selected.get(key);
    if (!prior || (rank[opportunityLifecycle(entry)] ?? -1) > (rank[opportunityLifecycle(prior)] ?? -1)) {
      selected.set(key, entry);
    }
  }
  return [...selected.values()].sort((a, b) => String(b.observed_at ?? "").localeCompare(String(a.observed_at ?? "")));
}
