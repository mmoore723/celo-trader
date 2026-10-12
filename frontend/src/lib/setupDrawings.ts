import type { ChartAnnotation, ScannerOpportunity } from "./api";

export function setupDrawings(setup?: ScannerOpportunity): ChartAnnotation[] {
  if (!setup) return [];
  const details = setup.setup_details ?? {};
  const labels: Record<string, string> = {
    or_high: "Opening range high / resistance", or_low: "Opening range low / support",
    compression_high: "Compression resistance", compression_low: "Compression support",
    prior_high: "Prior high / resistance", prior_low: "Prior low / support",
    pullback_high: "Pullback high", pullback_low: "Pullback low",
    retest_level: "Retest level", reclaim_level: "Reclaim level", impulse_extreme: "Impulse extreme",
    gap_upper: "FVG upper edge", gap_lower: "FVG lower edge",
    fvg_high: "FVG upper edge", fvg_low: "FVG lower edge",
    v2_stop: "Setup invalidation", underlying_stop: "Setup invalidation",
    v2_target: "Underlying target", underlying_target: "Underlying target",
    v2_entry_reference: "Entry trigger", reference_945: "9:45 reference",
  };
  const rows: ChartAnnotation[] = [];
  const seen = new Set<string>();
  for (const [key, label] of Object.entries(labels)) {
    const value = details[key];
    if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) continue;
    if (seen.has(`${label}:${value}`)) continue;
    seen.add(`${label}:${value}`);
    rows.push({ id: `${setup.id}:${key}`, type: "hline", strategy: setup.strategy_id,
      label, ts: setup.trigger_bar || setup.observed_at, price: value,
      color: label.includes("invalidation") ? "#ef4444" : label.includes("target") ? "#16a34a" : "#6366f1" });
  }
  const low = details.gap_lower ?? details.fvg_low;
  const high = details.gap_upper ?? details.fvg_high;
  if (typeof low === "number" && typeof high === "number" && low > 0 && high > low)
    rows.push({ id: `${setup.id}:fvg`, type: "zone", strategy: setup.strategy_id, label: "Recorded FVG",
      ts: setup.trigger_bar || setup.observed_at, price_low: low, price_high: high, color: "#6366f1" });
  return rows;
}
