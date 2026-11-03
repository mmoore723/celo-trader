export function ruleLabel(key: string) {
  const labels: Record<string,string> = {
    minimum_dte: 'Minimum days until expiration', maximum_dte: 'Maximum days until expiration',
    minimum_premium: 'Minimum option price per share', maximum_premium: 'Maximum option price per share',
    maximum_spread_pct: 'Maximum bid/ask spread', primary_policy: 'Default contract choice',
    basis: 'Why this contract range is used', version: 'Contract rules version',
    target_r: 'Profit target, as a multiple of initial risk', max_hold_bars: 'Maximum completed candles held',
    atr_period: 'ATR lookback, in candles', ema_fast: 'Fast EMA period', ema_slow: 'Slow EMA period',
  };
  return labels[key] ?? key.replaceAll('_',' ').replace(/\b(pct|rsi|macd|ema|sma|atr|vwap)\b/g, word => word === 'pct' ? 'percent' : word.toUpperCase());
}
export function ruleValue(key: string, value: unknown): string {
  if (value == null) return 'Not recorded';
  if (key === 'maximum_spread_pct' && typeof value === 'number') return `${(value*100).toFixed(1)}%`;
  if (key.endsWith('_premium') && typeof value === 'number') return `$${value.toFixed(2)} ($${(value*100).toFixed(0)} per contract)`;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.map(item => ruleValue('',item)).join(', ');
  if (typeof value === 'object') return Object.entries(value).map(([k,v])=>`${ruleLabel(k)}: ${ruleValue(k,v)}`).join('; ');
  return String(value).replaceAll('_',' ');
}
