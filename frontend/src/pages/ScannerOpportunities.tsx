import { useEffect, useMemo, useState } from "react";
import { strategyName as displayStrategyName, strategyVersion as displayVersion, strategyVariant } from "../lib/strategyIdentity.js";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { SearchX } from "lucide-react";
import { api, type ScannerOpportunity, type StrategyResearchMatrix, type StrategyTickerResearchPair } from "../lib/api";
import { PageLoader } from "../components/PageLoader";
import { AuthoredExitEvidence } from "../components/AuthoredExitEvidence";
import { ExpirationStudy } from "../components/ExpirationStudy";
import { ProfitProtectionComparison, ReferenceContractTest } from "../components/ProfitProtectionComparison";
import { ResearchAnalyticsView } from "../components/research/ResearchAnalyticsView";
import { QualificationEvidence } from "../components/research/QualificationEvidence";
import { ResearchFilters, type AnalyticsStatus } from "../components/research/ResearchFilters";
import { collapseOpportunityEpisodes, opportunityDecisionTitle, opportunityLifecycle, opportunityReason } from "../lib/opportunitySemantics.js";
import { profitFactorText, researchActionLabel, researchPairVisible, researchProfitFactorText, sortResearchPairs } from "../lib/researchPairView.js";

const NAMES: Record<string, string> = {
  V2_ORB_PULLBACK: "Opening-Range Pullback", V2_SPY_TREND_CONT: "SPY Trend Continuation",
  V2_SPY_AFTERNOON_FVG: "SPY Afternoon FVG", V2_FAILED_OR_BREAK_VWAP_REVERSION: "SPY Failed-Range Recovery",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "TSLA Two-Leg Trend Pullback",
  CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG: "VWAP Pullback (10:30 Displacement)",
};
const todayEt = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const daysAgoEt = (days: number) => { const value = new Date(); value.setDate(value.getDate() - days); return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(value); };
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
      <div className="flex-1 min-w-52"><p className="text-sm font-semibold" style={{ color }}>{opportunityDecisionTitle(entry)}</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{displayStrategyName(NAMES[entry.strategy_id] ?? entry.strategy_id)}</p><p className="text-sm mt-2">{opportunityReason(entry)}</p></div>
      {entered && trade?.pnl != null && <div className="text-right"><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Result</p><p className="text-lg font-semibold" style={{ color: Number(trade.pnl) >= 0 ? "var(--positive)" : "var(--negative)" }}>{money(trade.pnl)}</p></div>}
    </div>
    <details className="mt-3 border-t pt-3" style={{ borderColor: "var(--border)" }}><summary className="text-xs font-medium cursor-pointer" style={{ color: "var(--accent)" }}>Show recorded details</summary><div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs" style={{ color: "var(--ink-muted)" }}><p><b>Direction:</b> {entry.direction || "—"}</p><p><b>Contract:</b> {trade?.contract_symbol || contract.symbol || "Not selected"}</p><p><b>Quantity:</b> {entry.planned_quantity ?? trade?.contracts ?? "—"}</p><p><b>Entry:</b> {money(trade?.entry_price ?? entry.contract_preview?.planned_entry_price ?? entry.entry_plan?.estimated_entry_price)}</p></div></details>
  </article>;
}

type ExitMeasurement = StrategyResearchMatrix["strategies"][number]["exit_measurement"];

function ResearchRow({ pair, strategyName, strategyVersion, backtest, exitMeasurement }: { pair: StrategyTickerResearchPair; strategyName: string; strategyVersion: string; backtest: { profit_factor?: number | "infinite" | "no fills"; trades?: number; scope?: string; historical_test_through?: string }; exitMeasurement: ExitMeasurement }) {
  const status = pair.recommendation?.qualified
    ? { label: "Research qualified", color: "var(--positive)" }
    : { label: "Not yet qualified", color: "var(--warning)" };
  const resultState = pair.option_results > 0
    ? status.label
    : pair.setups > 0 ? "Setup found · no option matched"
      : pair.diagnosis === "entry_tuning" ? "Needs entry tuning" : "Building baseline";
  const plan = pair.improvement_tests?.[0];
  const testedProfitFactor = backtest.profit_factor === "no fills" ? null : backtest.profit_factor ?? null;
  const extraPlans = pair.improvement_tests?.slice(1) ?? [];
  return <article className="card overflow-hidden" style={{ borderLeft: `4px solid ${status.color}` }}>
    <div className="grid gap-3 p-3 lg:grid-cols-[minmax(14rem,1.35fr)_minmax(19rem,1fr)_minmax(18rem,1.2fr)] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2"><strong className="text-base">{pair.ticker}</strong><span className={`badge ${pair.tradable ? "badge-green" : "badge-blue"}`}>{pair.tradable ? "TRADING ON" : "TESTING"}</span><span className="text-xs font-semibold" style={{ color: status.color }}>{resultState}</span></div>
        <p className="text-sm truncate mt-1">{displayStrategyName(strategyName)} · {displayVersion(strategyVersion)}</p>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{pair.first_data_date ? `Data since ${evidenceDate(pair.first_data_date)} · ${pair.market_days} market days` : "No market data collected for this ticker yet"}</p>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{pair.raw_observations} raw trigger{pair.raw_observations === 1 ? "" : "s"} → {pair.setups} distinct research play{pair.setups === 1 ? "" : "s"} → {pair.option_results} priced result{pair.option_results === 1 ? "" : "s"}</p>
        {pair.tradable && backtest.trades != null && backtest.trades > 0 && <p className="text-xs mt-1 font-medium" style={{ color: "var(--ink-muted)" }}>{backtest.historical_test_through ? `Tested through ${evidenceDate(backtest.historical_test_through)}` : "Reviewed test"}: PF {profitFactorText(testedProfitFactor)} · {backtest.trades} results</p>}
      </div>
      <div>
        <div className="grid grid-cols-4 gap-2 text-center">
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>All-results PF</span><strong title={pair.profit_factor === "infinite" ? "There are wins but no gross losses yet, so a numeric PF cannot be calculated." : undefined}>{researchProfitFactorText(pair.profit_factor, pair.option_results)}</strong></div>
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>Priced tests</span><strong>{pair.option_results}</strong></div>
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>Wins</span><strong>{pair.win_rate_pct == null ? "—" : `${pair.win_rate_pct}%`}</strong></div>
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>P&amp;L</span><strong style={{ color: pair.option_results === 0 ? "var(--ink-muted)" : pair.net_one_contract_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>{pair.option_results === 0 ? "—" : money(pair.net_one_contract_pnl)}</strong></div>
        </div>
        <QualificationEvidence evidence={pair.recommendation} />
      </div>
      <div className="rounded-lg px-3 py-2" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface-raised))", border: "1px solid color-mix(in srgb, var(--accent) 24%, var(--border))" }}>
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>Next experiment</span>
        <strong className="text-sm block mt-0.5">{plan?.title ?? researchActionLabel(pair.diagnosis)}</strong>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{plan?.test ?? pair.next_action}</p>
      </div>
    </div>
    {pair.authored_exit_evidence && <div className="px-3 pb-2 text-xs"><AuthoredExitEvidence evidence={pair.authored_exit_evidence} /></div>}
    {pair.profit_protection_comparison && <div className="px-3 pb-2 text-xs"><ProfitProtectionComparison comparison={pair.profit_protection_comparison} /></div>}
    {pair.reference_contract_test && <div className="px-3 pb-2 text-xs"><ReferenceContractTest test={pair.reference_contract_test} /></div>}
    <details className="px-3 pb-3 text-xs">
      <summary className="cursor-pointer font-medium" style={{ color: "var(--accent)" }}>Evidence and test plan</summary>
      {pair.expiration_study && <div className="mt-2"><ExpirationStudy study={pair.expiration_study} /></div>}
      <p className="mt-2">Overlapping tests remain included in the research results, but do not add independent evidence.</p>
      <div className="grid gap-2 mt-3 sm:grid-cols-2 lg:grid-cols-4" style={{ color: "var(--ink-muted)" }}>
        <p><b>Research plays:</b> {pair.setups} across {pair.market_days} data days</p>
        <p><b>Usable option prices:</b> {pair.quote_coverage_pct == null ? "—" : `${pair.quote_coverage_pct}%`}</p>
        <p><b>Stock moved correctly:</b> {pair.direction_accuracy == null ? "—" : `${pair.direction_accuracy}% of ${pair.direction_results}`}</p>
        <p><b>Measured:</b> {exitMeasurement.authored_exit_collected ? `${exitMeasurement.timed_minutes}-minute strategy exit` : `${exitMeasurement.timed_minutes}-minute check`}</p>
        {!exitMeasurement.authored_exit_collected && <p className="sm:col-span-2"><b>Real exit:</b> {exitMeasurement.authored_exit} · {exitMeasurement.authored_collector_enabled ? "Tracking new research plays" : "Not measured yet"}</p>}
        {pair.option_results > 0 && <p><b>Average result:</b> {money(pair.average_one_contract_pnl)}</p>}
        {pair.option_results > 0 && <p><b>Typical result:</b> {money(pair.median_one_contract_pnl)}</p>}
        {pair.option_results > 0 && <p><b>Largest running drop:</b> {money(pair.maximum_drawdown_one_contract)}</p>}
        {pair.rule_rejected > 0 && <p><b>Filtered by current rule:</b> {pair.rule_rejected}</p>}
        {pair.previous_version_rows > 0 && <p><b>Earlier-version setups kept separate:</b> {pair.previous_version_rows}</p>}
        {pair.rule_unscored > 0 && <p><b>Current-version setups missing proof:</b> {pair.rule_unscored}</p>}
        {pair.stale_or_replayed > 0 && <p><b>Late signals ignored:</b> {pair.stale_or_replayed}</p>}
        {pair.mistimed_quotes_ignored > 0 && <p><b>Late prices ignored:</b> {pair.mistimed_quotes_ignored}</p>}
        {pair.legacy_option_profiles_ignored > 0 && <p><b>Rows using a different option test:</b> {pair.legacy_option_profiles_ignored}</p>}
        {pair.older_profit_factor != null && <p><b>Before {pair.comparison_split_date ?? "the comparison date"} PF:</b> {profitFactorText(pair.older_profit_factor)}</p>}
        {pair.newer_profit_factor != null && <p><b>From {pair.comparison_split_date ?? "the comparison date"} PF:</b> {profitFactorText(pair.newer_profit_factor)}</p>}
      </div>
      {backtest.trades != null && backtest.trades > 0 && <p className="mt-3" style={{ color: "var(--ink-muted)" }}><b>{backtest.historical_test_through ? `Tests through ${evidenceDate(backtest.historical_test_through)}` : "Saved test"}:</b> PF {profitFactorText(backtest.profit_factor === "no fills" ? null : backtest.profit_factor ?? null)} · {backtest.trades} results</p>}
      {extraPlans.length > 0 && <div className="grid gap-2 mt-3 md:grid-cols-3">{extraPlans.map(item => <div key={item.title} className="rounded-lg p-2" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}><b>{item.title}</b><p className="mt-1" style={{ color: "var(--ink-muted)" }}>{item.evidence}</p><p className="mt-1">{item.test}</p></div>)}</div>}
      <div className="flex flex-wrap gap-2 mt-3">
        {pair.exit_comparison.map(exit => <span key={exit.minutes} className="badge">{exit.minutes} min: PF {profitFactorText(exit.profit_factor)} ({exit.option_results}){exit.mistimed_quotes_ignored ? ` · ${exit.mistimed_quotes_ignored} late ignored` : ""}</span>)}
      </div>
      {pair.contract_tests.length > 0 && <div className="mt-3"><p className="font-medium">Which option choice is working?</p><div className="flex flex-wrap gap-2 mt-2">{pair.contract_tests.map(test => <span key={test.policy} className="badge">{test.label}: PF {profitFactorText(test.profit_factor)} ({test.option_results})</span>)}</div></div>}
    </details>
  </article>;
}

export function ScannerOpportunities({ view = "decisions", embedded = false }: { view?: "decisions" | "research"; embedded?: boolean }) {
  const [date, setDate] = useState(todayEt());
  const [selected, setSelected] = useState("all");
  const [tickerSearch, setTickerSearch] = useState("");
  const [debouncedTicker, setDebouncedTicker] = useState("");
  const [researchFilter, setResearchFilter] = useState("passing");
  const [researchView, setResearchView] = useState<"list" | "analytics">("list");
  const [startDate, setStartDate] = useState(daysAgoEt(89));
  const [endDate, setEndDate] = useState(todayEt());
  const [analyticsTickers, setAnalyticsTickers] = useState<string[]>([]);
  const [analyticsStatuses, setAnalyticsStatuses] = useState<AnalyticsStatus[]>([]);
  useEffect(() => { const timer = window.setTimeout(() => setDebouncedTicker(tickerSearch.trim().toUpperCase()), 300); return () => window.clearTimeout(timer); }, [tickerSearch]);

  const { data, isLoading, error } = useQuery({ queryKey: ["scanner-opportunities", date], queryFn: () => api.signals.opportunities({ date, limit: 1000 }), enabled: view === "decisions", refetchInterval: 15_000 });
  const resultsQuery = useInfiniteQuery({
    queryKey: ["strategy-research-results", startDate, endDate, selected, debouncedTicker, researchFilter],
    queryFn: ({ pageParam, signal }) => api.strategyHealth.researchResults({ startDate, endDate, page: pageParam, pageSize: 24, ticker: debouncedTicker, strategyId: selected, filter: researchFilter }, signal),
    initialPageParam: 1,
    getNextPageParam: last => last.pagination.has_more ? last.pagination.page + 1 : undefined,
    enabled: view === "research" && researchView === "list",
    staleTime: 60_000,
    refetchInterval: query => query.state.data?.pages[0]?.snapshot?.refreshing ? 5_000 : 60_000,
  });
  const matrix = resultsQuery.data?.pages[0];
  const { data: analytics, isLoading: analyticsLoading, error: analyticsError, isFetching: analyticsFetching, isPlaceholderData: analyticsPending } = useQuery({
    queryKey: ["strategy-research-analytics", startDate, endDate, analyticsTickers, analyticsStatuses],
    queryFn: ({ signal }) => api.strategyHealth.researchAnalytics({ startDate, endDate, tickers: analyticsTickers, statuses: analyticsStatuses }, signal),
    enabled: view === "research" && researchView === "analytics",
    staleTime: 60_000,
    refetchInterval: query => query.state.data?.snapshot?.refreshing ? 5_000 : 60_000,
  });
  const decisions = useMemo(() => collapseOpportunityEpisodes(data?.entries ?? []).filter(entry => opportunityLifecycle(entry) !== "research"), [data?.entries]);
  const allRows = useMemo(() => (resultsQuery.data?.pages ?? []).flatMap(page => page.strategies.flatMap(strategy => strategy.pairs.map(pair => ({ pair, strategy })))), [resultsQuery.data?.pages]);
  const researchPairs = useMemo(() => sortResearchPairs(allRows), [allRows]);
  const allPairs = useMemo(() => allRows.map(row => row.pair), [allRows]);
  const groupedResearchPairs = useMemo(() => [
    { key: "ready", title: "Ready to review", note: "Enough proof passed the goal and safety checks.", rows: researchPairs.filter(row => row.pair.diagnosis === "ready") },
    { key: "work", title: "Needs work", note: "The next test is shown on each row.", rows: researchPairs.filter(row => researchPairVisible(row.pair, "attention")) },
    { key: "testing", title: "Still testing", note: "The bot is collecting more clean results before deciding.", rows: researchPairs.filter(row => row.pair.diagnosis !== "ready" && !researchPairVisible(row.pair, "attention")) },
  ].filter(group => group.rows.length > 0), [researchPairs]);
  const entered = decisions.filter(entry => entry.outcome === "entered").length;
  const unfilled = decisions.filter(entry => entry.reason_code === "entry_price_not_reached").length;
  const skipped = decisions.filter(entry => opportunityLifecycle(entry) === "stopped" && entry.reason_code !== "entry_price_not_reached").length;
  const loadedPriced = allPairs.reduce((sum, pair) => sum + pair.option_results, 0);
  const snapshot = researchView === "list" ? matrix?.snapshot : analytics?.snapshot;
  const fetching = researchView === "list" ? resultsQuery.isFetching : analyticsFetching;
  if (view === "decisions" && isLoading && !data) return <PageLoader label="Bot Decisions" />;

  return <div className={`${embedded ? "space-y-4" : "page-container space-y-4"}`}>
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>{view === "decisions" ? "Before an order" : "Research pulse"}</p><h1 className="text-xl font-semibold mt-1">{view === "decisions" ? "Bot Decisions" : "Strategy + Ticker Lab"}</h1><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>{view === "decisions" ? "See why the bot entered, could not fill, or skipped each setup." : "Compare research performance or inspect the evidence behind each strategy and ticker."}</p></div>{view === "decisions" && <label className="text-xs" style={{ color: "var(--ink-muted)" }}>Trading day<input className="input ml-2" type="date" value={date} onChange={event => setDate(event.target.value)} /></label>}</header>
    {view === "decisions" ? <><div className="grid grid-cols-3 gap-3">{[["Trades entered", entered, "var(--positive)"], ["Orders not filled", unfilled, "var(--warning)"], ["Setups skipped", skipped, "var(--negative)"]].map(([label, value, color]) => <div className="card p-3" key={String(label)}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold" style={{ color: String(color) }}>{String(value)}</p></div>)}</div>{error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load decisions: {(error as Error).message}</div> : decisions.length ? <div className="space-y-3">{decisions.map(entry => <DecisionCard key={entry.id} entry={entry} />)}</div> : <div className="card p-8 text-center"><SearchX size={24} className="mx-auto" /><p className="mt-2 font-medium">No setup reached the trading path on this day.</p></div>}</> : <>
      <div className="flex gap-2"><button type="button" className={`btn ${researchView === "list" ? "btn-primary" : "btn-ghost"}`} onClick={() => setResearchView("list")}>Results list</button><button type="button" className={`btn ${researchView === "analytics" ? "btn-primary" : "btn-ghost"}`} onClick={() => setResearchView("analytics")}>Analytics</button></div>
      <p role="status" className="text-xs" style={{ color: "var(--ink-muted)" }}>{fetching ? "Loading your selection..." : snapshot?.refreshing ? "Showing saved results while fresh research is calculated." : ""}{snapshot && ` Results updated ${new Date(snapshot.updated_at * 1000).toLocaleTimeString()}.`}</p>
      {researchView === "analytics" && <ResearchFilters startDate={startDate} endDate={endDate} onStartDate={setStartDate} onEndDate={setEndDate} availableTickers={analytics?.available_tickers ?? matrix?.available_tickers ?? []} tickers={analyticsTickers} onTickers={setAnalyticsTickers} statuses={analyticsStatuses} onStatuses={setAnalyticsStatuses} />}
      {researchView === "analytics" ? (analyticsLoading && !analytics) || analyticsPending ? <PageLoader label="Research analytics" /> : analyticsError ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load analytics: {(analyticsError as Error).message}</div> : analytics ? <ResearchAnalyticsView data={analytics} /> : null :
      resultsQuery.isLoading && !matrix ? <PageLoader label="Research results" /> : resultsQuery.error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load research: {(resultsQuery.error as Error).message}</div> : matrix ? <>
        <div className="card overflow-hidden"><div className="grid gap-px grid-cols-2 lg:grid-cols-4" style={{ background: "var(--border)" }}>{[["At PF goal", matrix.result_counts.passing], ["Has priced results", matrix.result_counts.results], ["Signals without priced results", matrix.result_counts.no_option], ["No setup yet", matrix.result_counts.no_setup]].map(([label, value]) => <div key={String(label)} className="p-3" style={{ background: "var(--surface-raised)" }}><strong className="text-xl block">{value}</strong><span className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</span></div>)}</div><div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-3 py-2 text-xs" style={{ color: "var(--ink-muted)", background: "color-mix(in srgb, var(--accent) 5%, var(--surface-raised))" }}><span><b>{matrix.ticker_count}</b> tickers collected</span><span><b>{matrix.strategy_count}</b> strategies tested</span>{matrix.scanner_source_size > 0 && <span><b>{matrix.scanner_source_size.toLocaleString()}</b> optionable symbols screened · <b>{matrix.scanner_shortlist_size}</b> selected today</span>}<span>Goal PF <b>{matrix.target_profit_factor.toFixed(1)}</b></span></div></div>
        <div className="card p-4 space-y-3"><div className="flex flex-wrap items-end gap-3"><label className="text-sm font-medium min-w-56 flex-1">Strategy<select className="select w-full mt-2" value={selected} onChange={event => setSelected(event.target.value)}><option value="all">All strategies</option>{matrix.available_strategies.map(strategy => <option key={strategy.strategy_id} value={strategy.strategy_id}>{displayStrategyName(strategy.display_name)}{strategyVariant(strategy.strategy_id) ? ` · ${strategyVariant(strategy.strategy_id)}` : ""}</option>)}</select></label><label className="text-sm font-medium min-w-36">From<input className="input w-full mt-2" type="date" value={startDate} max={endDate} onChange={event => setStartDate(event.target.value)} /></label><label className="text-sm font-medium min-w-36">Through<input className="input w-full mt-2" type="date" value={endDate} min={startDate} onChange={event => setEndDate(event.target.value)} /></label><label className="text-sm font-medium min-w-40">Ticker<input className="input w-full mt-2 uppercase" type="search" placeholder="META" value={tickerSearch} onChange={event => setTickerSearch(event.target.value)} /></label><div className="flex flex-wrap gap-2" aria-label="Research result filters">{[["passing", `At profit goal (${matrix.result_counts.passing})`], ["attention", `Needs work (${matrix.result_counts.attention})`], ["results", `Has results (${matrix.result_counts.results})`], ["no_option", `Signals without priced results (${matrix.result_counts.no_option})`], ["no_setup", `No setup (${matrix.result_counts.no_setup})`], ["all", `Everything (${matrix.result_counts.all})`]].map(([value, label]) => <button key={value} type="button" className={`btn btn-sm ${researchFilter === value ? "btn-primary" : "btn-ghost"}`} aria-pressed={researchFilter === value} onClick={() => setResearchFilter(value)}>{label}</button>)}</div></div>{tickerSearch.trim() && <div className="rounded-lg px-3 py-2 text-sm" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface-raised))", color: "var(--ink-muted)" }}><strong style={{ color: "var(--ink)" }}>{tickerSearch.trim().toUpperCase()}</strong> · {matrix.pagination.total} matching rows · {loadedPriced} priced tests loaded</div>}<p className="text-xs" style={{ color: "var(--ink-muted)" }}>Signals without priced results means an entry signal fired, but no completed option result has usable pricing yet. PF compares total wins with total losses. A win-only sample says “No losses yet” until a loss gives PF a denominator.</p></div>
        {resultsQuery.isPlaceholderData ? <PageLoader label="Matching research results" /> : <div className="space-y-6">{groupedResearchPairs.map(group => <section key={group.key} className="space-y-2"><div className="flex flex-wrap items-baseline gap-2"><h2 className="text-base font-semibold">{group.title}</h2><span className="badge">{group.rows.length}</span><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{group.note}</p></div>{group.rows.map(({ pair, strategy }) => <ResearchRow key={`${strategy.strategy_id}-${pair.ticker}`} pair={pair} strategyName={strategy.display_name} strategyVersion={strategy.version} backtest={strategy.backtest} exitMeasurement={strategy.exit_measurement} />)}</section>)}</div>}
        {!resultsQuery.isPlaceholderData && resultsQuery.hasNextPage && <div className="flex justify-center"><button type="button" className="btn btn-ghost" disabled={resultsQuery.isFetching} onClick={() => resultsQuery.fetchNextPage()}>{resultsQuery.isFetchingNextPage ? "Loading…" : `Load more (${matrix.pagination.total - allRows.length} remaining)`}</button></div>}
        {!resultsQuery.isPlaceholderData && !researchPairs.length && <div className="card p-8 text-center">No strategy-ticker pairs match these filters yet.</div>}
        <details className="card p-4 text-xs"><summary className="cursor-pointer font-medium">How the proof works</summary><p className="mt-2" style={{ color: "var(--ink-muted)" }}>{matrix.cost_model}. Every distinct trigger is tested, including overlapping plays. Recommendations use 20 non-overlapping completed tests: first 14 and latest 6 each need PF 1.5+, a positive typical result, and no winner supplying over 35% of gains. No minimum day count. Research results are not broker fills; no trading switch changes automatically.</p></details>
      </> : <div className="card p-8 text-center">No research results are available yet.</div>}
    </>}
  </div>;
}
