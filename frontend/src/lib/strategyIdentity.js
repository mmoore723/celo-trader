const names = {
  CTX_1H_SQUEEZE_MACD_LONG: "Hourly Squeeze",
  CTX_VWAP_PULLBACK_KER10_LONG: "VWAP Pullback (1-Hour KER)",
  CTX_ORB_NR7_OR_INSIDE: "Context-Filtered ORB (NR7 / Inside)",
  TV_SUPERTREND_REVERSAL_V4: "SuperTrend Reversal",
  V2_VWAP_REVERSION_RTH: "VWAP Reversion",
  V2_TURTLE_SOUP_RTH: "Turtle Soup Reversal",
  V2_RANGE_SWEEP_RECLAIM: "Range Sweep Reclaim (Calls)",
  V2_ORB_CONFIRMED_BREAKOUT: "Confirmed Opening-Range Breakout",
  V2_OPENING_MOMENTUM_RTH_EXPLORATORY: "Opening Momentum",
  V2_MIDDAY_BREAKDOWN: "Midday Breakdown",
  V2_FAIR_VALUE_GAP: "Fair Value Gap",
  V2_EMA_PULLBACK_RTH: "EMA Pullback",
  V2_ORB_PULLBACK: "Opening-Range Pullback",
  V2_SPY_TREND_CONT: "Trend Continuation",
  V2_TREND_CONT: "Trend Continuation",
  RESEARCH_QQQ_TREND_V2: "Trend Continuation",
  V2_SPY_AFTERNOON_FVG: "Afternoon Fair Value Gap",
  V2_FAILED_OR_BREAK_VWAP_REVERSION: "Failed-Range Recovery",
  RESEARCH_FAILED_RANGE_V2: "Failed-Range Recovery",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "Two-Leg Trend Pullback",
  V2_GAP_FILL_RTH: "Gap Fill",
  V2_AFTERNOON_COMPRESSION_BREAKOUT: "Afternoon Compression Breakout",
  V2_AFTERNOON_REVERSAL: "Afternoon Reversal",
  V2_SPY_ORB_RSI_MACD_SHORT: "ORB RSI/MACD Short",
  V2_IMPULSE_ANCHORED_VWAP_PULLBACK: "Impulse Anchored VWAP Pullback",
  RESEARCH_CTX_ORB_ATR10_V2: "Context-Filtered ORB (ATR10)",
  CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG: "VWAP 10:30 Displacement",
  V2_VWAP_PULLBACK: "VWAP Pullback",
  INST_ORB: "Opening Range Breakout", BOS_MSS: "Break of Structure",
  VWAP_PB: "VWAP Pullback", FVG: "Fair Value Gap", IFVG: "Inverted Fair Value Gap",
  MID_BRK: "Mid-Day Breakdown", AFT_REV: "Afternoon Reversal",
  TREND_CONT: "Trend Continuation", CHAN_BREAK: "Channel Rejection",
  LIQ_SWEEP: "Liquidity Sweep", RECOVERED_UNTRACKED: "Recovered trade (strategy not recorded)",
  "TSLA Opening-Range Pullback": "Opening-Range Pullback",
  "SPY Trend Continuation": "Trend Continuation",
  "SPY Afternoon Fair Value Gap": "Afternoon Fair Value Gap",
  "SPY Afternoon FVG": "Afternoon Fair Value Gap",
  "SPY Failed-Range Recovery": "Failed-Range Recovery",
  "TSLA Two-Leg Trend Pullback": "Two-Leg Trend Pullback",
};

export function strategyName(name) {
  if (typeof name === 'string' && name.startsWith('APPROVED_')) return strategyName(name.slice(9));
  return names[name] ?? (name || "Not recorded");
}

// Event names describe the recorded event. Percentages shared by several
// policies must come from the frozen policy, never from today's settings.
export function exitReason(reason) {
  if (!reason) return 'Exit reason not recorded';
  const key = reason.split(/[\s(]/)[0];
  const premium = key.match(/^premium_(\d+)pct$/);
  if (premium) return `${premium[1]}% Premium Gain`;
  const giveback = key.match(/^giveback_(\d+)pct$/);
  if (giveback) return `${giveback[1]}% Peak-Profit Giveback`;
  const timer = key.match(/(?:markout_|selected_test_|time_cap_(?:loser_)?|timebox_|failed_range_)(\d+)m/);
  if (timer) return `${timer[1]}-Minute Time Limit`;
  const early = key.match(/^early_momentum_stop_(\d+)pct/);
  if (early) return `${early[1]}% Early Loss Stop`;
  const labels = {
    adverse_3x5m_10pct_loss: '3-Candle / 10% Loss Fail-Safe',
    trend_partial_profit: 'Half Profit Take + Peak-Profit Giveback',
    stage1_trend_profit_profit_take: 'Half Profit Take',
    trend_profit_giveback: 'Remaining Contracts: Peak-Profit Giveback',
    tsla_giveback_65_35: '$65 Profit Activation / 35% Peak-Profit Giveback',
    momentum_dead_exit: 'Momentum Exit', atr_trail_stop: 'ATR Trailing Stop',
    trail_stop: 'Trailing Stop', research_atr_trailing_stop: 'ATR Trailing Stop',
    structural_stop_bar_high: 'Structural Stop', trend_cont_underlying_stop: 'Structural Stop',
    trend_cont_underlying_2r_target: '2R Price Target', research_underlying_2r_target: '2R Price Target',
    vwap_breach_profitable: 'VWAP Breach', vwap_trend_dead: 'VWAP Trend Exit',
    peak_giveback: 'Peak-Profit Giveback', manual_journal: 'Manually Recorded Exit',
    panic: 'Panic Close', kill_lock_force_close: 'Account Safety Exit',
    simplified_chandelier_3atr: '3-ATR Chandelier Stop', simplified_hard_stop: 'Hard Stop',
    research_late_entry_quote: 'Late Entry Quote', research_missing_bars: 'Missing Candles',
    trend_cont_missing_bars: 'Missing Candles',
    auto_reconciled_no_broker_position: 'Reconciled: No Broker Position',
    reconciliation_never_filled: 'Reconciled: Entry Never Filled',
    broker_reconciled_replacement_fill: 'Reconciled Replacement Fill',
  };
  if (labels[key]) return labels[key];
  if (/session_(?:close|flatten|hard_cutoff)/.test(key)) return 'Session Close';
  if (key.startsWith('stage1_')) return 'Partial Profit Take';
  return key.replace(/^research_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Normalize presentation fields only. IDs, versions, evidence and submitted
// settings remain untouched, including nested activation specifications.
export function normalizeStrategyLabels(value) {
  if (Array.isArray(value)) return value.map(normalizeStrategyLabels);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
    ["display_name", "strategy_name"].includes(key) && typeof item === "string"
      ? strategyName(item) : normalizeStrategyLabels(item)]));
}

export function strategyVariant(id) {
  return id === "V2_SPY_TREND_CONT" ? "30-minute exit"
    : id === "V2_TREND_CONT" ? "Structure-based exit" : "";
}

export function strategyVersion(version) {
  return version ? `v${version.replace(/^v/, "")}` : "";
}

// Presentation grouping only. Never merge execution IDs, settings or evidence.
export function groupStrategies(strategies) {
  const groups = new Map();
  for (const strategy of strategies) {
    const name = names[strategy.strategy_id] ?? strategyName(strategy.display_name);
    if (!groups.has(name)) groups.set(name, { name, strategies: [] });
    groups.get(name).strategies.push(strategy);
  }
  return [...groups.values()];
}
