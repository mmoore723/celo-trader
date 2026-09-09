function timeframeCounts(ticker) {
  return (ticker.timeframes ?? []).reduce(
    (counts, timeframe) => {
      if (timeframe.bias === "up") counts.up += 1;
      if (timeframe.bias === "down") counts.down += 1;
      return counts;
    },
    { up: 0, down: 0 },
  );
}

/**
 * A plain-language read of today's trade conditions.
 *
 * This deliberately ignores research-only tickers. It describes whether the
 * bot's authorized ticker/strategy pairs are lining up cleanly; it does not
 * predict whether the whole market will rise or fall.
 */
export function premarketDayOutlook(tickers) {
  const tradable = tickers.filter((ticker) => ticker.tradeable_today);

  if (tradable.length === 0) {
    return {
      level: "waiting",
      label: "WAITING",
      emoji: "🌫️",
      summary: "No tradable setup is ready yet.",
      detail: "The bot is still watching for a clean match on a ticker it may trade.",
      tradableCount: 0,
      clearCount: 0,
      mixedCount: 0,
    };
  }

  const reads = tradable.map((ticker) => {
    const { up, down } = timeframeCounts(ticker);
    const strongestSide = Math.max(up, down);
    return {
      clear: ticker.readiness_score >= 80 && strongestSide >= 4,
      usable: ticker.readiness_score >= 65 && strongestSide >= 3,
      mixed: up >= 2 && down >= 2,
    };
  });
  const clearCount = reads.filter((read) => read.clear).length;
  const usableCount = reads.filter((read) => read.usable).length;
  const mixedCount = reads.filter((read) => read.mixed).length;

  if (clearCount >= 2) {
    return {
      level: "green",
      label: "GREEN · CLEAR",
      emoji: "☀️",
      summary: `Clear setups are forming on ${clearCount} tradable tickers.`,
      detail: "Several tickers agree across timeframes. Wait for each strategy's exact entry trigger.",
      tradableCount: tradable.length,
      clearCount,
      mixedCount,
    };
  }

  if (clearCount === 1 || usableCount >= 2) {
    return {
      level: "yellow",
      label: "YELLOW · SELECTIVE",
      emoji: "⛅",
      summary: clearCount === 1
        ? "One tradable ticker looks clear; the rest need more proof."
        : "Some tradable setups are forming, but the picture is not fully clear.",
      detail: "Take only a clean strategy trigger. Do not treat a high score by itself as an entry.",
      tradableCount: tradable.length,
      clearCount,
      mixedCount,
    };
  }

  return {
    level: "red",
    label: "RED · CHOPPY",
    emoji: "🌧️",
    summary: mixedCount > 0
      ? `${mixedCount} tradable ticker${mixedCount === 1 ? " has" : "s have"} mixed timeframe signals.`
      : "The tradable tickers do not have a clean setup yet.",
    detail: "Conditions look choppy or weak. Wait for the timeframes and strategy trigger to line up.",
    tradableCount: tradable.length,
    clearCount,
    mixedCount,
  };
}
