import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SearchX } from "lucide-react";
import { api, type ScannerOpportunity, type StrategyTickerResearchPair } from "../lib/api";
import { PageLoader } from "../components/PageLoader";
import { collapseOpportunityEpisodes, opportunityDecisionTitle, opportunityLifecycle, opportunityReason } from "../lib/opportunitySemantics.js";
import { profitFactorText, researchActionLabel, researchPairVisible, sortResearchPairs } from "../lib/researchPairView.js";

const NAMES: Record<string, string> = {
  V2_ORB_PULLBACK: "Opening-Range Pullback", V2_SPY_TREND_CONT: "SPY Trend Continuation",
  V2_SPY_AFTERNOON_FVG: "SPY Afternoon FVG", V2_FAILED_OR_BREAK_VWAP_REVERSION: "SPY Failed-Range Recovery",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "TSLA Two-Leg Trend Pullback",
  CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG: "VWAP Pullback (10:30 Displacement)",
};
const todayEt = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const evidenceDate = (value?: string) => value ? new Date(`${value}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
const time = (value?: string | null) => value ? new Date(value).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) : "—";
const money = (value?: number | null) => value == null ? "—" : `$${Number(value).toFixed(2)}`;

function DecisionCard({ entry }: { entry: ScannerOpportunity }) {
  const stage = opportunityLifecycle(entry), entered = stage === "entered", noFill = entry.reason_code === "entry_price_not_reached";
  const color = entered ? "var(--positive)" : noFill ? "var(--warning)" : stage === "stopped" ? "var(--negative)" : "var(--accent)";
  const trade = entry.trade, contract = entry.contract ?? {};
  return <article className="card p-4" style={{ borderLeft: `5px solid ${color}` }}>
    <div className="flex flex-wrap items-start gap-3">
      <div className="w-20"><p className="text-xs" style={{ color: "var(--ink-faint)" }}>{time(entry.observed_at)} ET</p><p className="text-lg font-semibold">{entry.ticker}</p></div>
      <div className="flex-1 min-w-52"><p className="text-sm font-semibold" style={{ color }}>{opportunityDecisionTitle(entry)}</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{NAMES[entry.strategy_id] ?? entry.strategy_id}</p><p className="text-sm mt-2">{opportunityReason(entry)}</p></div>
      {entered && trade?.pnl != null && <div className="text-right"><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Result</p><p className="text-lg font-semibold" style={{ color: Number(trade.pnl) >= 0 ? "var(--positive)" : "var(--negative)" }}>{money(trade.pnl)}</p></div>}
    </div>
    <details className="mt-3 border-t pt-3" style={{ borderColor: "var(--border)" }}><summary className="text-xs font-medium cursor-pointer" style={{ color: "var(--accent)" }}>Show recorded details</summary><div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs" style={{ color: "var(--ink-muted)" }}><p><b>Direction:</b> {entry.direction || "—"}</p><p><b>Contract:</b> {trade?.contract_symbol || contract.symbol || "Not selected"}</p><p><b>Quantity:</b> {entry.planned_quantity ?? trade?.contracts ?? "—"}</p><p><b>Entry:</b> {money(trade?.entry_price ?? entry.contract_preview?.planned_entry_price ?? entry.entry_plan?.estimated_entry_price)}</p></div></details>
  </article>;
}

const STATUS: Record<StrategyTickerResearchPair["status"], { label: string; color: string }> = {
  working: { label: "Working", color: "var(--positive)" },
  promising: { label: "Looks promising", color: "var(--accent)" },
  losing_so_far: { label: "Losing so far", color: "var(--negative)" },
  needs_tuning: { label: "Needs tuning", color: "var(--warning)" },
  not_working: { label: "Not working", color: "var(--negative)" },
  collecting: { label: "Collecting results", color: "var(--ink-muted)" },
  no_setups: { label: "No setups yet", color: "var(--ink-muted)" },
};

function ResearchRow({ pair, strategyName, strategyVersion, backtest, exitMinutes }: { pair: StrategyTickerResearchPair; strategyName: string; strategyVersion: string; backtest: { profit_factor?: number | "infinite" | "no fills"; trades?: number; scope?: string; historical_test_through?: string }; exitMinutes: number }) {
  const status = STATUS[pair.status];
  return <article className="card p-4">
    <div className="grid gap-3 lg:grid-cols-[minmax(14rem,1.5fr)_repeat(4,minmax(5rem,.55fr))_minmax(14rem,1.5fr)] lg:items-center">
      <div>
        <div className="flex flex-wrap items-center gap-2"><strong className="text-lg">{pair.ticker}</strong><span className={`badge ${pair.tradable ? "badge-green" : "badge-blue"}`}>{pair.tradable ? "TRADING ON" : "RESEARCH"}</span></div>
        <p className="text-sm mt-1">{strategyName} · v{strategyVersion}</p>
        {backtest.trades != null && backtest.trades > 0 && <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{backtest.historical_test_through ? `Tests through ${evidenceDate(backtest.historical_test_through)}` : "Saved test"}: PF {profitFactorText(backtest.profit_factor === "no fills" ? null : backtest.profit_factor ?? null)} · {backtest.trades} results</p>}
        <p className="text-xs font-semibold mt-1" style={{ color: status.color }}>{status.label}</p>
        {pair.leading_contract_test && pair.leading_contract_test.option_results > 0 && <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Most option evidence: {pair.leading_contract_test.label} · PF {profitFactorText(pair.leading_contract_test.profit_factor)} ({pair.leading_contract_test.option_results})</p>}
      </div>
      <div><span className="text-xs block" style={{ color: "var(--ink-muted)" }}>Current PF</span><strong>{profitFactorText(pair.profit_factor)}</strong></div>
      <div><span className="text-xs block" style={{ color: "var(--ink-muted)" }}>Current results</span><strong>{pair.option_results}</strong><span className="text-xs block" style={{ color: "var(--ink-muted)" }}>{pair.option_result_days} days</span></div>
      <div><span className="text-xs block" style={{ color: "var(--ink-muted)" }}>Wins</span><strong>{pair.win_rate_pct == null ? "—" : `${pair.win_rate_pct}%`}</strong></div>
      <div><span className="text-xs block" style={{ color: "var(--ink-muted)" }}>1-contract P&amp;L</span><strong style={{ color: pair.net_one_contract_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>{money(pair.net_one_contract_pnl)}</strong></div>
      <div className="rounded-lg p-3" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
        <strong className="text-sm">{researchActionLabel(pair.diagnosis)}</strong>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{pair.next_action}</p>
      </div>
    </div>
    <details className="mt-3 pt-3 text-xs" style={{ borderTop: "1px solid var(--border)" }}>
      <summary className="cursor-pointer font-medium" style={{ color: "var(--accent)" }}>See why</summary>
      <div className="grid gap-2 mt-3 sm:grid-cols-2 lg:grid-cols-4" style={{ color: "var(--ink-muted)" }}>
        <p><b>Independent setups:</b> {pair.setups} across {pair.market_days} data days</p>
        <p><b>Usable option prices:</b> {pair.quote_coverage_pct == null ? "—" : `${pair.quote_coverage_pct}%`}</p>
        <p><b>Stock moved correctly:</b> {pair.direction_accuracy == null ? "—" : `${pair.direction_accuracy}% of ${pair.direction_results}`}</p>
        <p><b>Compared exit:</b> {exitMinutes} minutes</p>
        {pair.rule_rejected > 0 && <p><b>Filtered by current rule:</b> {pair.rule_rejected}</p>}
        {pair.previous_version_rows > 0 && <p><b>Earlier-version setups kept separate:</b> {pair.previous_version_rows}</p>}
        {pair.rule_unscored > 0 && <p><b>Current-version setups missing proof:</b> {pair.rule_unscored}</p>}
        {pair.stale_or_replayed > 0 && <p><b>Late signals ignored:</b> {pair.stale_or_replayed}</p>}
        {pair.mistimed_quotes_ignored > 0 && <p><b>Late prices ignored:</b> {pair.mistimed_quotes_ignored}</p>}
        {pair.legacy_option_profiles_ignored > 0 && <p><b>Rows using a different option test:</b> {pair.legacy_option_profiles_ignored}</p>}
        {pair.older_profit_factor != null && <p><b>Before {pair.comparison_split_date ?? "the comparison date"} PF:</b> {profitFactorText(pair.older_profit_factor)}</p>}
        {pair.newer_profit_factor != null && <p><b>From {pair.comparison_split_date ?? "the comparison date"} PF:</b> {profitFactorText(pair.newer_profit_factor)}</p>}
      </div>
      <div className="flex flex-wrap gap-2 mt-3">
        {pair.exit_comparison.map(exit => <span key={exit.minutes} className="badge">{exit.minutes} min: PF {profitFactorText(exit.profit_factor)} ({exit.option_results}){exit.mistimed_quotes_ignored ? ` · ${exit.mistimed_quotes_ignored} late ignored` : ""}</span>)}
      </div>
      {pair.contract_tests.length > 0 && <div className="mt-3"><p className="font-medium">Which option choice is working?</p><div className="flex flex-wrap gap-2 mt-2">{pair.contract_tests.map(test => <span key={test.policy} className="badge">{test.label}: PF {profitFactorText(test.profit_factor)} ({test.option_results})</span>)}</div></div>}
    </details>
  </article>;
}

export function ScannerOpportunities({ view = "decisions", embedded = false }: { view?: "decisions" | "research"; embedded?: boolean }) {
  const [date, setDate] = useState(todayEt()), [selected, setSelected] = useState("all"), [researchFilter, setResearchFilter] = useState("evidence");
  const { data, isLoading, error } = useQuery({ queryKey: ["scanner-opportunities", date], queryFn: () => api.signals.opportunities({ date, limit: 1000 }), refetchInterval: 15_000 });
  const { data: matrix, isLoading: matrixLoading, error: matrixError } = useQuery({ queryKey: ["strategy-research-matrix"], queryFn: () => api.strategyHealth.researchMatrix(90), refetchInterval: 60_000 });
  const decisions = useMemo(() => collapseOpportunityEpisodes(data?.entries ?? []).filter(entry => opportunityLifecycle(entry) !== "research"), [data?.entries]);
  const researchPairs = useMemo(() => {
    const rows = (matrix?.strategies ?? []).flatMap(strategy => strategy.pairs.map(pair => ({ pair, strategy })));
    return sortResearchPairs(rows.filter(row => selected === "all" || row.strategy.strategy_id === selected).filter(row => researchPairVisible(row.pair, researchFilter)));
  }, [matrix, selected, researchFilter]);
  const measuredPairs = useMemo(() => (matrix?.strategies ?? []).flatMap(strategy => strategy.pairs).filter(pair => pair.option_results > 0), [matrix]);
  const entered = decisions.filter(entry => entry.outcome === "entered").length;
  const unfilled = decisions.filter(entry => entry.reason_code === "entry_price_not_reached").length;
  const skipped = decisions.filter(entry => opportunityLifecycle(entry) === "stopped" && entry.reason_code !== "entry_price_not_reached").length;
  if (view === "decisions" && isLoading && !data) return <PageLoader label="Bot Decisions" />;
  return <div className={`${embedded ? "space-y-4" : "page-container space-y-4"}`}>
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>{view === "decisions" ? "Before an order" : "Strategy + ticker evidence"}</p><h1 className="text-xl font-semibold mt-1">{view === "decisions" ? "Bot Decisions" : "Research Results"}</h1><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>{view === "decisions" ? "See why the bot entered, could not fill, or skipped each setup." : "See which strategy works with which ticker. Research observes only and cannot place an order."}</p></div>{view === "decisions" && <label className="text-xs" style={{ color: "var(--ink-muted)" }}>Trading day<input className="input ml-2" type="date" value={date} onChange={event => setDate(event.target.value)} /></label>}</header>
    {view === "decisions" ? <><div className="grid grid-cols-3 gap-3">{[["Trades entered", entered, "var(--positive)"], ["Orders not filled", unfilled, "var(--warning)"], ["Setups skipped", skipped, "var(--negative)"]].map(([label, value, color]) => <div className="card p-3" key={String(label)}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold" style={{ color: String(color) }}>{String(value)}</p></div>)}</div>{error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load decisions: {(error as Error).message}</div> : decisions.length ? <div className="space-y-3">{decisions.map(entry => <DecisionCard key={entry.id} entry={entry} />)}</div> : <div className="card p-8 text-center"><SearchX size={24} className="mx-auto" /><p className="mt-2 font-medium">No setup reached the trading path on this day.</p></div>}</> : <>
      <div className="card p-4"><h2 className="font-semibold">Which strategy works on which ticker?</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Goal: PF {matrix?.target_profit_factor.toFixed(1) ?? "1.5"}. Every row is one strategy + ticker. Repeated scans count once. Rows from a different rule version, missing prices, and late prices are not counted.</p></div>
      {matrixLoading && !matrix ? <PageLoader label="Research results" /> : matrixError ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load research: {(matrixError as Error).message}</div> : matrix ? <>
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          {[["Pairs with results", measuredPairs.length], ["Working", measuredPairs.filter(pair => pair.status === "working").length], ["Promising", measuredPairs.filter(pair => pair.status === "promising").length], ["Need a change", measuredPairs.filter(pair => ["losing_so_far", "needs_tuning", "not_working"].includes(pair.status)).length]].map(([label, value]) => <div key={String(label)} className="card p-3"><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><strong className="text-xl">{value}</strong></div>)}
        </div>
        <div className="card p-4 grid gap-3 sm:grid-cols-2">
          <label className="text-sm font-medium">Strategy<select className="select w-full mt-2" value={selected} onChange={event => setSelected(event.target.value)}><option value="all">All strategies</option>{matrix.strategies.map(strategy => <option key={strategy.strategy_id} value={strategy.strategy_id}>{strategy.display_name}</option>)}</select></label>
          <label className="text-sm font-medium">Show<select className="select w-full mt-2" value={researchFilter} onChange={event => setResearchFilter(event.target.value)}><option value="evidence">Pairs with setups</option><option value="attention">Needs attention</option><option value="passing">Working or promising</option><option value="all">Everything being watched</option></select></label>
        </div>
        <div className="space-y-3">{researchPairs.map(({ pair, strategy }) => <ResearchRow key={`${strategy.strategy_id}-${pair.ticker}`} pair={pair} strategyName={strategy.display_name} strategyVersion={strategy.version} backtest={strategy.backtest} exitMinutes={strategy.exit_minutes} />)}</div>
        {!researchPairs.length && <div className="card p-8 text-center">No strategy–ticker pairs match these filters yet.</div>}
        <details className="card p-4 text-xs"><summary className="cursor-pointer font-medium">How results are calculated</summary><p className="mt-2" style={{ color: "var(--ink-muted)" }}>{matrix.cost_model}. The same trigger counts once, and overlapping fixed-hold trades are excluded. “Working” requires PF 1.5+, at least 20 option results, at least 8 setup days, and the most recent dated test window must also pass.</p></details>
      </> : <div className="card p-8 text-center">No research results are available yet.</div>}
    </>}
  </div>;
}
