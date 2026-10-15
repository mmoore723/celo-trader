export function journalDate(value) {
  if (!value) return null;
  const text = String(value);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(text)) return null;
  const parsed = new Date(text);
  if (!Number.isFinite(parsed.getTime())) return null;
  // Journal timestamps without offsets are stored in New York local time.
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(text)) return text.slice(0, 10);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(parsed);
}

export function inJournalWindow(trade, window, from = "", now = new Date()) {
  if (window === "all" || (window === "custom" && !from)) return true;
  const today = journalDate(now.toISOString());
  const cut = new Date(`${today}T12:00:00Z`);
  if (window === "week") cut.setUTCDate(cut.getUTCDate() - 6);
  if (window === "month") cut.setUTCDate(cut.getUTCDate() - 29);
  const start = window === "custom" ? from : cut.toISOString().slice(0, 10);
  return [trade.entry_time, trade.exit_time].some(value => {
    const date = journalDate(value);
    return date !== null && date >= start && date <= today;
  });
}

export function journalRealizedSummary(trades) {
  const closed = trades.filter(t => t.status === "closed" && typeof t.pnl === "number" && Number.isFinite(t.pnl));
  return {
    pnl: closed.reduce((sum, t) => sum + t.pnl, 0),
    closed: closed.length,
    winRate: closed.length ? 100 * closed.filter(t => t.pnl > 0).length / closed.length : null,
  };
}
