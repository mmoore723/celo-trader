/** Deterministic practice scoring. No AI call and no future candle input. */
export function expectedLearningAnswers(category, direction) {
  if (category === "rejected_missing_condition" || category === "false_breakout_or_chop") return ["reject"];
  if (category === "ambiguous_no_trade") return ["wait", "reject"];
  return [String(direction).toLowerCase() === "bullish" ? "call" : "put"];
}

export function scoreLearningAnswer(category, direction, answer) {
  return expectedLearningAnswers(category, direction).includes(answer);
}
