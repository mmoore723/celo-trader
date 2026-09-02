/**
 * Keep strategy PF display semantics independent from React so empty samples,
 * all-win samples, and minimum-evidence rules remain regression-testable.
 */

export function strategyPerformanceForId(rows, strategyId) {
  if (!Array.isArray(rows)) return null;
  return rows.find((row) => row?.strategy_id === strategyId) ?? null;
}

export function strategyPerformanceState(row, target = 1.5, minimumTrades = 30) {
  const trades = Number(row?.trades ?? 0);
  const wins = Number(row?.wins ?? 0);
  const losses = Number(row?.losses ?? 0);
  const rawPf = Number(row?.profit_factor ?? 0);
  const infinite = trades > 0 && wins > 0 && losses === 0;
  const pf = infinite ? Number.POSITIVE_INFINITY : rawPf;
  const hasResult = trades > 0;
  const enoughEvidence = trades >= minimumTrades;
  return {
    trades,
    hasResult,
    enoughEvidence,
    meetsTarget: hasResult && enoughEvidence && pf >= target,
    pfLabel: !hasResult ? "not recorded" : infinite ? "∞" : rawPf.toFixed(2),
  };
}
