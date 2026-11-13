const names = {
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
  return names[name] ?? (name || "Not recorded");
}

export function exitReason(reason) {
  return ({premium_2pct:'2% Premium Gain',premium_25pct:'25% Premium Gain',
    giveback_25pct:'25% Peak-Profit Giveback',trend_partial_profit:'Take half at +25%, then 25% profit giveback',stage1_trend_profit_profit_take:'Half sold at +25%',trend_profit_giveback:'Remaining contracts: 25% profit giveback'})[reason] ?? reason ?? 'Not recorded';
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
