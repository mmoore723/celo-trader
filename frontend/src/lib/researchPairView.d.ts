import type { StrategyResearchMatrix, StrategyTickerResearchPair } from "./api";

type ResearchStrategy = StrategyResearchMatrix["strategies"][number];
type ResearchRow = { pair: StrategyTickerResearchPair; strategy: ResearchStrategy };

export function researchActionLabel(diagnosis: StrategyTickerResearchPair["diagnosis"]): string;
export function profitFactorText(value: number | "infinite" | null): string;
export function researchPairVisible(pair: StrategyTickerResearchPair, filter: string): boolean;
export function sortResearchPairs<T extends ResearchRow>(rows: T[]): T[];
