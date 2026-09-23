import { useState } from "react";
import { strategyName } from "../../lib/strategyIdentity.js";
import type { ResearchAnalytics, ResearchAnalyticsRow, ResearchPairAnalytics } from "../../lib/api";

const pfText = (value: ResearchAnalyticsRow["profit_factor"]) => value === "infinite" ? "No losses yet" : value == null ? "Not priced" : value.toFixed(2);
const cash = (value: number | null) => value == null ? "Not measured" : `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
const labels = { at_goal: "At PF goal", needs_work: "Needs work", collecting: "Collecting results" };
const color = (status: ResearchPairAnalytics["status"]) => status === "at_goal" ? "var(--positive)" : status === "needs_work" ? "var(--negative)" : "var(--ink-muted)";
const pageSize = 25;

export function ResearchAnalyticsView({ data }: { data: ResearchAnalytics }) {
  const [minTen, setMinTen] = useState(false);
  const [page, setPage] = useState(1);
  const pairs = data.pairs.filter(row => !minTen || row.priced_tests >= 10);
  const pages = Math.max(1, Math.ceil(pairs.length / pageSize));
  const current = Math.min(page, pages);
  const visible = pairs.slice((current - 1) * pageSize, current * pageSize);
  const quality = data.data_quality;
  return <div className="space-y-4">
    <section className="card p-4">
      <h2 className="font-semibold">Research pipeline</h2>
      <div className="grid gap-3 mt-3 sm:grid-cols-2 xl:grid-cols-4">
        {[["Raw triggers", data.pipeline.raw_triggers], ["Distinct research plays", data.pipeline.distinct_plays], ["Priced results", data.pipeline.priced_results], ["Completed tests", data.pipeline.completed_tests]].map(([label, value], index) => <div className="rounded-lg p-3" style={{ background: "var(--surface-sunken)", border: "1px solid var(--border)" }} key={label}><span className="text-xs" style={{ color: "var(--ink-muted)" }}>{index + 1}. {label}</span><strong className="block text-2xl mt-1">{Number(value).toLocaleString()}</strong></div>)}
      </div>
      <p className="text-xs mt-3" style={{ color: "var(--ink-muted)" }}>Priced results are completed strategy-exit tests with usable option prices, so those counts can match. Counts are strategy/ticker tests, not unique market events.</p>
      <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3 text-sm">
        <span>Missing candles or late entry prices: <strong style={{ color: quality.affected_tests ? "var(--warning)" : "var(--ink)" }}>{quality.affected_pct == null ? "Not measured" : `${quality.affected_pct}%`}</strong> ({quality.affected_tests}/{quality.tracked_tests} tracked tests)</span>
        <span>Global PF <strong>{pfText(data.summary.profit_factor)}</strong></span>
        <span>Win rate <strong>{data.summary.win_rate_pct == null ? "Not measured" : `${data.summary.win_rate_pct}%`}</strong></span>
        <span>After costs <strong>{cash(data.summary.net_pnl)}</strong></span>
        <span>Tracked open tests <strong>{data.summary.active_tests}</strong></span>
      </div>
      <p className="text-xs mt-2" style={{ color: "var(--ink-muted)" }}>Data-health coverage: {quality.covered_pairs}/{quality.total_pairs} pairs have tracked exit evidence. Untracked tests are not counted as healthy. P&amp;L uses the card's one-contract research cost model, not broker fills.</p>
    </section>

    <section className="card p-4">
      <div className="flex flex-wrap justify-between items-center gap-3"><div><h2 className="font-semibold">Pair progress and performance</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Sorted by strategy-exit PF. Progress counts non-overlapping completed tests toward 20. Typical profit is the median after costs.</p></div><label className="text-sm flex gap-2 items-center"><input type="checkbox" checked={minTen} onChange={event => { setMinTen(event.target.checked); setPage(1); }} />Minimum 10 priced tests</label></div>
      <div className="flex flex-wrap gap-4 text-xs mt-3">{Object.entries(labels).map(([status, label]) => <span key={status} style={{ color: color(status as ResearchPairAnalytics["status"]) }}>{label}: {status === "at_goal" ? "PF >= 1.5" : status === "needs_work" ? "PF < 1.0" : "PF 1.0 to <1.5 or not priced"}</span>)}</div>
      <div className="overflow-x-auto mt-4"><table className="table w-full text-sm"><thead><tr>{["Ticker / strategy", "Version", "Non-overlapping / target", "Completed / priced", "Win rate", "Strategy exit PF", "Typical profit", "After-cost P&L", "Data health / 2R"].map(label => <th key={label} className="text-left whitespace-nowrap">{label}</th>)}</tr></thead><tbody>{visible.map(row => <tr key={`${row.strategy_id}:${row.ticker}`}>
        <td><strong>{row.ticker}</strong><span className="block text-xs">{strategyName(row.strategy_name)}</span><span className="text-xs" style={{ color: color(row.status) }}>{labels[row.status]}</span></td>
        <td className="text-xs whitespace-nowrap">{row.version || "Not recorded"}</td>
        <td className="min-w-40"><span>{row.independent_tests} / {row.target_tests}</span><progress className="block w-full h-2 mt-1" aria-label={`${row.ticker} ${row.strategy_name} test progress`} value={Math.min(row.independent_tests, row.target_tests)} max={row.target_tests} style={{ accentColor: color(row.status) }} /></td>
        <td>{row.completed_tests} / {row.priced_tests}</td>
        <td>{row.win_rate_pct == null ? "Not measured" : `${row.win_rate_pct}%`}</td>
        <td style={{ color: color(row.status) }}>{pfText(row.profit_factor)}</td>
        <td className="whitespace-nowrap">{cash(row.typical_profit)}</td>
        <td className="whitespace-nowrap" style={{ color: row.net_pnl < 0 ? "var(--negative)" : "var(--positive)" }}>{row.priced_tests ? cash(row.net_pnl) : "Not priced"}</td>
        <td className="text-xs min-w-48">{row.health_available ? <><span style={{ color: row.missing_candles || row.missing_quotes || row.late_entry_prices || row.pending_quotes ? "var(--warning)" : "var(--ink-muted)" }}>{row.missing_candles} missing candles / {row.missing_quotes} missing quotes<br />{row.late_entry_prices} late entries / {row.pending_quotes} awaiting quotes</span><span className="block mt-1" style={{ color: row.target_2r_hits ? "var(--positive)" : "var(--ink-muted)" }}>{row.target_2r_hits} recorded 2R target exits</span></> : "Health / 2R not tracked"}</td>
      </tr>)}</tbody></table></div>
      {!pairs.length && <p className="py-6 text-sm">No pairs match these filters.</p>}
      <div className="flex justify-between items-center gap-3 mt-4 text-sm"><span>{pairs.length} pairs · Page {current} of {pages}</span><div className="flex gap-2"><button className="btn btn-secondary" disabled={current <= 1} onClick={() => setPage(current - 1)}>Previous</button><button className="btn btn-secondary" disabled={current >= pages} onClick={() => setPage(current + 1)}>Next</button></div></div>
    </section>

    <section className="card p-4"><h2 className="font-semibold">Ticker leaderboard</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Each ticker appears once, ranked by net after-cost research P&amp;L across its strategy tests. Overlapping tests are not an account return.</p><div className="mt-3 max-h-96 overflow-auto"><table className="table w-full text-sm"><thead><tr><th>Rank</th><th>Ticker</th><th>Priced tests</th><th>Win rate</th><th>Net after costs</th></tr></thead><tbody>{data.tickers.filter(row => row.priced_tests > 0).map((row, index) => <tr key={row.ticker}><td>{index + 1}</td><td className="font-semibold">{row.ticker}</td><td>{row.priced_tests}</td><td>{row.win_rate_pct}%</td><td style={{ color: row.net_pnl < 0 ? "var(--negative)" : "var(--positive)" }}>{cash(row.net_pnl)}</td></tr>)}</tbody></table>{!data.tickers.some(row => row.priced_tests > 0) && <p className="py-4">No priced ticker results in this selection.</p>}</div></section>
  </div>;
}
