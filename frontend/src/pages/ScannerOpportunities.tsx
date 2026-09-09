import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SearchX } from "lucide-react";
import { api, type ScannerOpportunity, type StrategyTickerResearchPair } from "../lib/api";
import { PageLoader } from "../components/PageLoader";
import { collapseOpportunityEpisodes, opportunityDecisionTitle, opportunityLifecycle, opportunityReason } from "../lib/opportunitySemantics.js";
import { numericProfitFactor, profitFactorText, researchActionLabel, researchPairVisible, researchProfitFactorText, sortResearchPairs } from "../lib/researchPairView.js";

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
  const progress = Math.min(100, Math.round(Math.min(pair.option_results / 20, pair.option_result_days / 8) * 100));
  const plan = pair.improvement_tests?.[0];
  const testedProfitFactor = backtest.profit_factor === "no fills" ? null : backtest.profit_factor ?? null;
  const extraPlans = pair.improvement_tests?.slice(1) ?? [];
  return <article className="card overflow-hidden" style={{ borderLeft: `4px solid ${status.color}` }}>
    <div className="grid gap-3 p-3 lg:grid-cols-[minmax(14rem,1.35fr)_minmax(19rem,1fr)_minmax(18rem,1.2fr)] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2"><strong className="text-base">{pair.ticker}</strong><span className={`badge ${pair.tradable ? "badge-green" : "badge-blue"}`}>{pair.tradable ? "TRADING ON" : "TESTING"}</span><span className="text-xs font-semibold" style={{ color: status.color }}>{status.label}</span></div>
        <p className="text-sm truncate mt-1">{strategyName} · v{strategyVersion}</p>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{pair.first_data_date ? `Data since ${evidenceDate(pair.first_data_date)} · ${pair.market_days} market days` : "No market data collected for this ticker yet"}</p>
        {pair.tradable && backtest.trades != null && backtest.trades > 0 && <p className="text-xs mt-1 font-medium" style={{ color: "var(--ink-muted)" }}>{backtest.historical_test_through ? `Tested through ${evidenceDate(backtest.historical_test_through)}` : "Reviewed test"}: PF {profitFactorText(testedProfitFactor)} · {backtest.trades} results</p>}
      </div>
      <div>
        <div className="grid grid-cols-4 gap-2 text-center">
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>Test PF</span><strong title={pair.profit_factor === "infinite" ? "There are wins but no gross losses yet, so a numeric PF cannot be calculated." : undefined}>{researchProfitFactorText(pair.profit_factor, pair.option_results)}</strong></div>
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>Results</span><strong>{pair.option_results}</strong></div>
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>Wins</span><strong>{pair.win_rate_pct == null ? "—" : `${pair.win_rate_pct}%`}</strong></div>
          <div><span className="text-[11px] block" style={{ color: "var(--ink-muted)" }}>P&amp;L</span><strong style={{ color: pair.net_one_contract_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>{money(pair.net_one_contract_pnl)}</strong></div>
        </div>
        <div className="mt-2 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--surface-sunken, var(--border))" }} aria-label={`${progress}% of minimum evidence collected`}><div className="h-full rounded-full" style={{ width: `${progress}%`, background: "linear-gradient(90deg, var(--accent), var(--positive))" }} /></div>
        <p className="text-[11px] mt-1 text-right" style={{ color: "var(--ink-muted)" }}>{progress}% of minimum evidence</p>
      </div>
      <div className="rounded-lg px-3 py-2" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface-raised))", border: "1px solid color-mix(in srgb, var(--accent) 24%, var(--border))" }}>
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>Next experiment</span>
        <strong className="text-sm block mt-0.5">{plan?.title ?? researchActionLabel(pair.diagnosis)}</strong>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{plan?.test ?? pair.next_action}</p>
      </div>
    </div>
    <details className="px-3 pb-3 text-xs">
      <summary className="cursor-pointer font-medium" style={{ color: "var(--accent)" }}>Evidence and test plan</summary>
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
  const [date, setDate] = useState(todayEt()), [selected, setSelected] = useState("all"), [tickerSearch, setTickerSearch] = useState(""), [researchFilter, setResearchFilter] = useState("results");
  const { data, isLoading, error } = useQuery({ queryKey: ["scanner-opportunities", date], queryFn: () => api.signals.opportunities({ date, limit: 1000 }), refetchInterval: 15_000 });
  const { data: matrix, isLoading: matrixLoading, error: matrixError } = useQuery({ queryKey: ["strategy-research-matrix"], queryFn: () => api.strategyHealth.researchMatrix(90), refetchInterval: 60_000 });
  const decisions = useMemo(() => collapseOpportunityEpisodes(data?.entries ?? []).filter(entry => opportunityLifecycle(entry) !== "research"), [data?.entries]);
  const allRows = useMemo(() => (matrix?.strategies ?? []).flatMap(strategy => strategy.pairs.map(pair => ({ pair, strategy }))), [matrix]);
  const scopedRows = useMemo(() => {
    const wantedTicker = tickerSearch.trim().toUpperCase();
    return allRows.filter(row =>
      (selected === "all" || row.strategy.strategy_id === selected)
      && (!wantedTicker || row.pair.ticker.includes(wantedTicker))
    );
  }, [allRows, selected, tickerSearch]);
  const researchPairs = useMemo(() => sortResearchPairs(scopedRows.filter(row => researchPairVisible(row.pair, researchFilter))), [scopedRows, researchFilter]);
  const allPairs = useMemo(() => scopedRows.map(row => row.pair), [scopedRows]);
  const measuredPairs = useMemo(() => allPairs.filter(pair => pair.option_results > 0), [allPairs]);
  const passingNow = useMemo(() => measuredPairs.filter(pair => numericProfitFactor(pair.profit_factor) >= (matrix?.target_profit_factor ?? 1.5)), [matrix?.target_profit_factor, measuredPairs]);
  const needsWork = useMemo(() => allPairs.filter(pair => researchPairVisible(pair, "attention")), [allPairs]);
  const readyToReview = useMemo(() => allPairs.filter(pair => pair.diagnosis === "ready"), [allPairs]);
  const waiting = allPairs.length - measuredPairs.length;
  const groupedResearchPairs = useMemo(() => [
    { key: "ready", title: "Ready to review", note: "Enough proof passed the goal and safety checks.", rows: researchPairs.filter(row => row.pair.diagnosis === "ready") },
    { key: "work", title: "Needs work", note: "The next test is shown on each row.", rows: researchPairs.filter(row => researchPairVisible(row.pair, "attention")) },
    { key: "testing", title: "Still testing", note: "The bot is collecting more clean results before deciding.", rows: researchPairs.filter(row => row.pair.diagnosis !== "ready" && !researchPairVisible(row.pair, "attention")) },
  ].filter(group => group.rows.length > 0), [researchPairs]);
  const entered = decisions.filter(entry => entry.outcome === "entered").length;
  const unfilled = decisions.filter(entry => entry.reason_code === "entry_price_not_reached").length;
  const skipped = decisions.filter(entry => opportunityLifecycle(entry) === "stopped" && entry.reason_code !== "entry_price_not_reached").length;
  if (view === "decisions" && isLoading && !data) return <PageLoader label="Bot Decisions" />;
  return <div className={`${embedded ? "space-y-4" : "page-container space-y-4"}`}>
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>{view === "decisions" ? "Before an order" : "Research pulse"}</p><h1 className="text-xl font-semibold mt-1">{view === "decisions" ? "Bot Decisions" : "Strategy + Ticker Lab"}</h1><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>{view === "decisions" ? "See why the bot entered, could not fill, or skipped each setup." : "One row per strategy and ticker. See what is working now and the next experiment to run."}</p></div>{view === "decisions" && <label className="text-xs" style={{ color: "var(--ink-muted)" }}>Trading day<input className="input ml-2" type="date" value={date} onChange={event => setDate(event.target.value)} /></label>}</header>
    {view === "decisions" ? <><div className="grid grid-cols-3 gap-3">{[["Trades entered", entered, "var(--positive)"], ["Orders not filled", unfilled, "var(--warning)"], ["Setups skipped", skipped, "var(--negative)"]].map(([label, value, color]) => <div className="card p-3" key={String(label)}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold" style={{ color: String(color) }}>{String(value)}</p></div>)}</div>{error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load decisions: {(error as Error).message}</div> : decisions.length ? <div className="space-y-3">{decisions.map(entry => <DecisionCard key={entry.id} entry={entry} />)}</div> : <div className="card p-8 text-center"><SearchX size={24} className="mx-auto" /><p className="mt-2 font-medium">No setup reached the trading path on this day.</p></div>}</> : <>
      {matrixLoading && !matrix ? <PageLoader label="Research results" /> : matrixError ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load research: {(matrixError as Error).message}</div> : matrix ? <>
        <div className="card overflow-hidden">
          <div className="grid gap-px grid-cols-2 lg:grid-cols-4" style={{ background: "var(--border)" }}>
            {[["Ready to review", readyToReview.length], ["Has priced results", measuredPairs.length], ["Needs work", needsWork.length], ["Waiting for first result", waiting]].map(([label, value]) => <div key={String(label)} className="p-3" style={{ background: "var(--surface-raised)" }}><strong className="text-xl block">{value}</strong><span className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</span></div>)}
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-3 py-2 text-xs" style={{ color: "var(--ink-muted)", background: "color-mix(in srgb, var(--accent) 5%, var(--surface-raised))" }}>
            <span><b>{matrix.ticker_count}</b> tickers collected so far</span>
            <span><b>{matrix.strategy_count}</b> strategies tested on each</span>
            {matrix.scanner_source_size > 0 && <span><b>{matrix.scanner_source_size.toLocaleString()}</b> optionable symbols screened · <b>{matrix.scanner_shortlist_size}</b> selected today</span>}
            <span>Goal PF <b>{matrix.target_profit_factor.toFixed(1)}</b></span>
          </div>
        </div>
        <div className="card p-4 space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm font-medium min-w-64 flex-1">Strategy<select className="select w-full mt-2" value={selected} onChange={event => setSelected(event.target.value)}><option value="all">All strategies</option>{matrix.strategies.map(strategy => <option key={strategy.strategy_id} value={strategy.strategy_id}>{strategy.display_name}</option>)}</select></label>
            <label className="text-sm font-medium min-w-40">Ticker<input className="input w-full mt-2 uppercase" type="search" placeholder="META" value={tickerSearch} onChange={event => setTickerSearch(event.target.value)} /></label>
            <div className="flex flex-wrap gap-2" aria-label="Research result filters">
              {[["results", `Has results (${measuredPairs.length})`], ["attention", `Needs work (${needsWork.length})`], ["passing", `At PF goal (${passingNow.length})`], ["waiting", `Waiting (${waiting})`], ["all", `Everything (${allPairs.length})`]].map(([value, label]) => <button key={value} type="button" className={`btn btn-sm ${researchFilter === value ? "btn-primary" : "btn-ghost"}`} aria-pressed={researchFilter === value} onClick={() => setResearchFilter(value)}>{label}</button>)}
            </div>
          </div>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>PF compares total wins with total losses. A win-only sample says “No losses yet” until a loss gives PF a denominator.</p>
        </div>
        <div className="space-y-6">{groupedResearchPairs.map(group => <section key={group.key} className="space-y-2"><div className="flex flex-wrap items-baseline gap-2"><h2 className="text-base font-semibold">{group.title}</h2><span className="badge">{group.rows.length}</span><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{group.note}</p></div>{group.rows.map(({ pair, strategy }) => <ResearchRow key={`${strategy.strategy_id}-${pair.ticker}`} pair={pair} strategyName={strategy.display_name} strategyVersion={strategy.version} backtest={strategy.backtest} exitMinutes={strategy.exit_minutes} />)}</section>)}</div>
        {!researchPairs.length && <div className="card p-8 text-center">No strategy–ticker pairs match these filters yet.</div>}
        <details className="card p-4 text-xs"><summary className="cursor-pointer font-medium">How the proof works</summary><p className="mt-2" style={{ color: "var(--ink-muted)" }}>{matrix.cost_model}. The same trigger counts once, and overlapping tests are excluded. A recommendation requires PF 1.5+, at least 20 priced results, at least 8 result days, and passing results on the latest test dates.</p></details>
      </> : <div className="card p-8 text-center">No research results are available yet.</div>}
    </>}
  </div>;
}
