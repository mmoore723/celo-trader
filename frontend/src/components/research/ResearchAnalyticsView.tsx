import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ResearchAnalytics, ResearchAnalyticsRow } from "../../lib/api";

const pfNumber = (value: ResearchAnalyticsRow["profit_factor"]) => value === "infinite" ? 10 : Number(value ?? 0);
const pfText = (value: ResearchAnalyticsRow["profit_factor"]) => value === "infinite" ? "∞" : value == null ? "—" : value.toFixed(2);
const cash = (value: number) => `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(2)}`;
const statusLabel = { at_goal: "At goal", needs_work: "Needs work", testing: "Testing" } as const;

export function ResearchAnalyticsView({ data }: { data: ResearchAnalytics }) {
  const summary = data.summary;
  const finiteMax = Math.max(data.target_profit_factor, ...data.strategies.map(row => row.profit_factor === "infinite" ? 0 : Number(row.profit_factor ?? 0)));
  const chartRows = data.strategies.map(row => ({ ...row, chartPf: row.profit_factor === "infinite" ? finiteMax + 0.5 : pfNumber(row.profit_factor) }));
  const tickerRows = [...data.top_tickers.map(row => ({ ...row, group: "Top 5", gains: row.gross_profit, losses: -row.gross_loss })), ...data.bottom_tickers.map(row => ({ ...row, group: "Bottom 5", gains: row.gross_profit, losses: -row.gross_loss }))];
  return <div className="space-y-4">
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {[
        ["Global profit factor", pfText(summary.profit_factor)],
        ["Aggregate win rate", summary.win_rate_pct == null ? "—" : `${summary.win_rate_pct}%`],
        ["Net after-cost P&L", cash(summary.net_pnl)],
        ["Completed / active tests", `${summary.completed_tests} / ${summary.active_tests}`],
      ].map(([label, value]) => <div className="card p-4" key={label}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><strong className="text-2xl block mt-1">{value}</strong></div>)}
    </section>

    <section className="card p-4">
      <div className="flex items-baseline justify-between gap-3"><div><h2 className="font-semibold">Strategy comparison</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Ranked by after-cost profit factor. The line marks the 1.5 research goal.</p></div></div>
      <div className="mt-4" style={{ height: Math.max(260, chartRows.length * 30) }}>
        <ResponsiveContainer width="100%" height="100%"><BarChart data={chartRows} layout="vertical" margin={{ left: 12, right: 24 }}><CartesianGrid stroke="var(--border)" horizontal={false} /><XAxis type="number" domain={[0, "dataMax"]} /><YAxis type="category" dataKey="strategy_name" width={180} tick={{ fontSize: 11 }} /><Tooltip formatter={(value) => Number(value).toFixed(2)} /><ReferenceLine x={data.target_profit_factor} stroke="var(--warning)" strokeDasharray="5 4" /><Bar dataKey="chartPf" radius={[0, 4, 4, 0]}>{chartRows.map(row => <Cell key={row.strategy_id} fill={row.status === "at_goal" ? "var(--positive)" : row.status === "needs_work" ? "var(--negative)" : "var(--accent)"} />)}</Bar></BarChart></ResponsiveContainer>
      </div>
      <div className="overflow-x-auto mt-4"><table className="table w-full text-sm"><thead><tr><th>Strategy</th><th className="text-right">Triggers</th><th className="text-right">Priced</th><th className="text-right">Win rate</th><th className="text-right">PF</th><th className="text-right">Net P&amp;L</th><th>Status</th></tr></thead><tbody>{data.strategies.map(row => <tr key={row.strategy_id}><td className="font-medium">{row.strategy_name}</td><td className="text-right">{row.total_triggers}</td><td className="text-right">{row.priced_tests}</td><td className="text-right">{row.win_rate_pct == null ? "—" : `${row.win_rate_pct}%`}</td><td className="text-right">{pfText(row.profit_factor)}</td><td className="text-right" style={{ color: row.net_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>{cash(row.net_pnl)}</td><td><span className={`badge ${row.status === "at_goal" ? "badge-green" : ""}`}>{statusLabel[row.status]}</span></td></tr>)}</tbody></table></div>
    </section>

    <section className="card p-4">
      <h2 className="font-semibold">Ticker leaderboard</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Top 5 and bottom 5 screened tickers by realized after-cost P&amp;L.</p>
      <div className="mt-4 h-72"><ResponsiveContainer width="100%" height="100%"><BarChart data={tickerRows} layout="vertical" margin={{ left: 8, right: 24 }}><CartesianGrid stroke="var(--border)" horizontal={false} /><XAxis type="number" /><YAxis type="category" dataKey="ticker" width={54} /><Tooltip formatter={(value) => cash(Number(value))} /><ReferenceLine x={0} stroke="var(--ink-muted)" /><Bar dataKey="gains" name="Gross gains" stackId="performance" fill="var(--positive)" /><Bar dataKey="losses" name="Gross losses" stackId="performance" fill="var(--negative)" /></BarChart></ResponsiveContainer></div>
      <div className="grid gap-3 mt-4 lg:grid-cols-2">{[["Top 5 performers", data.top_tickers], ["Bottom 5 performers", data.bottom_tickers]].map(([title, rows]) => <div key={String(title)} className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border)" }}><h3 className="text-sm font-semibold p-3" style={{ background: "var(--surface-sunken)" }}>{String(title)}</h3>{(rows as ResearchAnalytics["tickers"]).map(row => <div key={row.ticker} className="grid grid-cols-[4rem_1fr_1fr] gap-2 px-3 py-2 text-sm border-t" style={{ borderColor: "var(--border)" }}><strong>{row.ticker}</strong><span>{row.win_rate_pct == null ? "No priced tests" : `${row.win_rate_pct}% wins`}</span><span className="text-right" style={{ color: row.net_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>{cash(row.net_pnl)}</span></div>)}</div>)}</div>
    </section>
  </div>;
}
