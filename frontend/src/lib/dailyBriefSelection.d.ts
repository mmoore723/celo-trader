export interface DailyBriefTickerSelection {
  selected: string;
  loading: boolean;
  pinnedTickers: string[];
  premarketTickers: string[];
  scannerTickers: string[];
}

export function preferredDailyBriefTicker(input: DailyBriefTickerSelection): string;
