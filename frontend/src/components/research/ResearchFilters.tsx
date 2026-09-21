export type AnalyticsStatus = "at_goal" | "needs_work" | "collecting";

export function ResearchFilters({
  startDate, endDate, onStartDate, onEndDate, availableTickers, tickers, onTickers,
  statuses, onStatuses,
}: {
  startDate: string; endDate: string; onStartDate: (value: string) => void; onEndDate: (value: string) => void;
  availableTickers: string[]; tickers: string[]; onTickers: (value: string[]) => void;
  statuses: AnalyticsStatus[]; onStatuses: (value: AnalyticsStatus[]) => void;
}) {
  const toggleStatus = (status: AnalyticsStatus) => onStatuses(statuses.includes(status) ? statuses.filter(item => item !== status) : [...statuses, status]);
  return <section className="card p-4 flex flex-wrap items-end gap-3">
    <label className="text-xs font-medium">From<input className="input block mt-1" type="date" value={startDate} max={endDate} onChange={event => onStartDate(event.target.value)} /></label>
    <label className="text-xs font-medium">Through<input className="input block mt-1" type="date" value={endDate} min={startDate} onChange={event => onEndDate(event.target.value)} /></label>
    <label className="text-xs font-medium min-w-48">Tickers<select className="select block w-full mt-1" value="" onChange={event => event.target.value && !tickers.includes(event.target.value) && onTickers([...tickers, event.target.value])}><option value="">Add ticker</option>{availableTickers.filter(ticker => !tickers.includes(ticker)).map(ticker => <option key={ticker}>{ticker}</option>)}</select></label>
    <div className="flex flex-wrap gap-2">{tickers.map(ticker => <button key={ticker} className="badge" type="button" onClick={() => onTickers(tickers.filter(item => item !== ticker))}>{ticker} ×</button>)}</div>
    <div className="flex flex-wrap gap-2 ml-auto" aria-label="Analytics status filters">{([['at_goal', 'At PF goal'], ['needs_work', 'Needs work'], ['collecting', 'Collecting results']] as [AnalyticsStatus, string][]).map(([value, label]) => <button key={value} type="button" className={`btn btn-sm ${statuses.includes(value) ? "btn-primary" : "btn-ghost"}`} aria-pressed={statuses.includes(value)} onClick={() => toggleStatus(value)}>{label}</button>)}</div>
  </section>;
}
