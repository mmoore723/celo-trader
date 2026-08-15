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
  const copies = {
    watching: { title: "Setup Developing", badge: "WATCHING", detail: "The chart pattern is not complete yet." },
    pricing: { title: "Checking Contract", badge: "PRICING", detail: "The setup reached option liquidity and affordability checks." },
    ready: { title: "Trade Ready", badge: "READY", detail: "A contract was selected; the bot is waiting for the recorded entry trigger." },
    stopped: { title: "Setup Stopped", badge: "STOPPED", detail: "A recorded rule prevented this setup from entering." },
    entered: { title: "New Trade Idea", badge: "ENTERED", detail: "The bot entered and linked the actual trade record." },
    research: { title: "Research Observation", badge: "RESEARCH", detail: "This observation was never authorized to place an order." },
  };
  return copies[lifecycle] ?? copies.watching;
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
