const names = {
  "TSLA Opening-Range Pullback": "Opening-Range Pullback",
  "SPY Trend Continuation": "Trend Continuation",
  "SPY Afternoon Fair Value Gap": "Afternoon Fair Value Gap",
  "SPY Afternoon FVG": "Afternoon Fair Value Gap",
  "SPY Failed-Range Recovery": "Failed-Range Recovery",
  "TSLA Two-Leg Trend Pullback": "Two-Leg Trend Pullback",
};

export function strategyName(name) {
  return names[name] ?? name;
}

export function strategyVariant(id) {
  return id === "V2_SPY_TREND_CONT" ? "30-minute exit"
    : id === "V2_TREND_CONT" ? "Structure-based exit" : "";
}

export function strategyVersion(version) {
  return version ? `v${version.replace(/^v/, "")}` : "";
}
