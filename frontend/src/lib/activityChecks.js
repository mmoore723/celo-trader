// Only recorded check results can color a card. Never infer readiness from prose.
export function activityChecks(entry) {
  const values = Array.isArray(entry.conditions) && entry.conditions.length
    ? entry.conditions : entry.checks;
  if (!Array.isArray(values)) return [];
  return values.filter(v => v && typeof v === 'object').map(v => {
    const status = String(v.status ?? v.state ?? '').toLowerCase();
    const state = v.passed === true ? 'passed' : v.passed === false ? 'failed'
      : ['passed', 'pass'].includes(status) ? 'passed'
      : ['failed', 'fail'].includes(status) ? 'failed'
      : ['evaluating', 'pending', 'priming'].includes(status) ? 'pending' : 'unknown';
    const name = v.name || v.label || 'Check';
    // This is the explicit history prerequisite emitted by the evaluators.
    // Do not classify candle-close entry triggers as missing history.
    const displayState = state === 'pending' && name === 'Completed candles' ? 'waiting' : state;
    return {name, state: displayState,
      reason: v.reason || v.detail || 'This update did not record an explanation.'};
  });
}
