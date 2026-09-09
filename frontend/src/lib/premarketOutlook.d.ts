import type { PremarketTicker } from "./api";

export interface PremarketDayOutlook {
  level: "waiting" | "green" | "yellow" | "red";
  label: string;
  emoji: string;
  summary: string;
  detail: string;
  tradableCount: number;
  clearCount: number;
  mixedCount: number;
}

export function premarketDayOutlook(tickers: PremarketTicker[]): PremarketDayOutlook;
