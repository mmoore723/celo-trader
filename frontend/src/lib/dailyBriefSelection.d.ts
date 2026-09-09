export interface DailyBriefTickerSelection {
  selected: string;
  loading: boolean;
  premarketTickers: string[];
}

export function preferredDailyBriefTicker(input: DailyBriefTickerSelection): string;
