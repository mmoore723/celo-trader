import type { ChartAnnotation, ScannerOpportunity, Trade } from "./api";

export function stockPositionDrawings(trade?: Trade, setup?: ScannerOpportunity): ChartAnnotation[] {
  if (!trade?.entry_time) return [];
  const details = setup?.trade?.id === trade.id && setup.ticker === trade.ticker ? setup.setup_details ?? {} : {};
  const value = (...values: unknown[]) => values.find(v => typeof v === "number" && Number.isFinite(v) && v > 0) as number | undefined;
  const saved = (label: string) => trade.annotations?.find(a => a.type === "hline" && a.label === label)?.price;
  const entry = value(details.v2_entry_reference, details.underlying_entry, saved("Entry trigger"));
  const stop = value(details.v2_stop, details.underlying_stop, saved("Setup invalidation"));
  const target = value(details.v2_target, details.underlying_target, saved("Underlying target"));
  if (entry == null) return [];
  const direction = trade.option_type === "put" || trade.direction === "short" ? -1 : 1;
  const risk = stop == null ? null : direction * (entry - stop);
  const reward = target == null ? null : direction * (target - entry);
  const ratio = risk != null && reward != null && risk > 0 && reward > 0 ? (reward / risk).toFixed(2) : null;
  const rows: ChartAnnotation[] = [];
  for (const [name, level, color] of [["Stock entry reference", entry, "#e0a000"],
    ["Stock target", reward != null && reward > 0 ? target : undefined, "#16a34a"],
    ["Stock stop", risk != null && risk > 0 ? stop : undefined, "#ef4444"]] as const) {
    if (level == null) continue;
    const change = direction * (level - entry) / entry * 100;
    const base = { id: `position:${trade.mode}:${trade.id}:${name}`, strategy: trade.strategy_id ?? "",
      ts: trade.entry_time, end_ts: trade.exit_time, color };
    rows.push({ ...base, type: "hline", price: level,
      label: `${name} $${level.toFixed(2)} | ${change >= 0 ? "+" : ""}${change.toFixed(2)}% | ${trade.contracts} contracts${ratio ? ` | R:R 1:${ratio}` : ""}` });
    if (level !== entry) rows.push({ ...base, id: `${base.id}:box`, type: "zone", label: name,
      price_low: Math.min(entry, level), price_high: Math.max(entry, level) });
  }
  return rows;
}
