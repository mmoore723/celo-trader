import type { ReviewedStrategyCatalogEntry } from './api';

// Teaching taxonomy only. Never changes execution IDs or policy selection.
export function learningFamily(s: Pick<ReviewedStrategyCatalogEntry, 'strategy_id' | 'display_name'>): string {
  const id = s.strategy_id;
  if (/FAILED_RANGE|FAILED_OR_BREAK/.test(id)) return 'Failed-Range Recovery';
  if (/ORB|OPENING_RANGE/.test(id)) return 'Opening-Range Breakout (ORB)';
  if (/VWAP.*PULLBACK|IMPULSE_ANCHORED_VWAP/.test(id)) return 'VWAP Pullback';
  if (/FVG|FAIR_VALUE_GAP/.test(id)) return 'Fair Value Gap (FVG)';
  if (/TWO_LEG/.test(id)) return 'Two-Leg Pullback';
  if (/TREND_CONT|QQQ_TREND/.test(id)) return 'Trend Continuation';
  return s.display_name.replace(/^(SPY|TSLA|QQQ)\s*[·:-]?\s*/, '');
}
