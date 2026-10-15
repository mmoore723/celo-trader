type JournalTrade = { entry_time?: string; exit_time?: string; status: string; pnl?: number | null };
export function journalDate(value?: string | null): string | null;
export function inJournalWindow(trade: JournalTrade, window: string, from?: string, now?: Date): boolean;
export function journalRealizedSummary(trades: JournalTrade[]): { pnl: number; closed: number; winRate: number | null };
