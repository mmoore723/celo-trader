import type { StrategyTickerResearchPair } from "./api";

export function settingsPairEvidenceRows(pairs: StrategyTickerResearchPair[], tradingTickers?: string[]): {
  pair: StrategyTickerResearchPair; trading: boolean;
}[];
