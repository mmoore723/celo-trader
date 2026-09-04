import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SearchX } from "lucide-react";
import { api, type ScannerOpportunity, type StrategyTickerResearchPair } from "../lib/api";
import { PageLoader } from "../components/PageLoader";
import { collapseOpportunityEpisodes, opportunityDecisionTitle, opportunityLifecycle, opportunityReason } from "../lib/opportunitySemantics.js";

const NAMES: Record<string, string> = {
  V2_ORB_PULLBACK: "Opening-Range Pullback", V2_SPY_TREND_CONT: "SPY Trend Continuation",
  V2_SPY_AFTERNOON_FVG: "SPY Afternoon FVG", V2_FAILED_OR_BREAK_VWAP_REVERSION: "SPY Failed-Range Recovery",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "TSLA Two-Leg Trend Pullback",
  CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG: "VWAP Pullback (10:30 Displacement)",
};
const todayEt = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
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
  needs_tuning: { label: "Needs tuning", color: "var(--warning)" },
  not_working: { label: "Not working", color: "var(--negative)" },
  collecting: { label: "Collecting results", color: "var(--ink-muted)" },
  no_setups: { label: "No setups yet", color: "var(--ink-muted)" },
};

function ResearchRow({ pair }: { pair: StrategyTickerResearchPair }) {
  const status = STATUS[pair.status];
  const pf = pair.profit_factor === "infinite" ? "∞" : typeof pair.profit_factor === "number" ? pair.profit_factor.toFixed(2) : "—";
  return <article className="rounded-lg p-3" style={{ border: "1px solid var(--border)", background: "var(--surface-raised)" }}>
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><strong className="text-lg">{pair.ticker}</strong><p className="text-sm font-semibold mt-1" style={{ color: status.color }}>{status.label}</p></div>
      <span className={`badge ${pair.tradable ? "badge-green" : "badge-blue"}`}>{pair.tradable ? "TRADING ON" : "RESEARCH ONLY"}</span>
    </div>
    <p className="text-xs mt-2" style={{ color: "var(--ink-muted)" }}>{pair.explanation}</p>
    <div className="grid grid-cols-3 gap-2 mt-3 text-center">
      <div><strong className="block">{pf}</strong><span className="text-xs" style={{ color: "var(--ink-muted)" }}>Profit factor</span></div>
      <div><strong className="block">{pair.option_results}</strong><span className="text-xs" style={{ color: "var(--ink-muted)" }}>Option results</span></div>
      <div><strong className="block">{pair.market_days}</strong><span className="text-xs" style={{ color: "var(--ink-muted)" }}>Days watched</span></div>
    </div>
  </article>;
}

export function ScannerOpportunities() {
  const [view, setView] = useState<"decisions" | "research">("decisions"), [date, setDate] = useState(todayEt()), [selected, setSelected] = useState("");
  const { data, isLoading, error } = useQuery({ queryKey: ["scanner-opportunities", date], queryFn: () => api.signals.opportunities({ date, limit: 1000 }), refetchInterval: 15_000 });
  const { data: matrix, isLoading: matrixLoading, error: matrixError } = useQuery({ queryKey: ["strategy-research-matrix"], queryFn: () => api.strategyHealth.researchMatrix(90), refetchInterval: 60_000 });
  const decisions = useMemo(() => collapseOpportunityEpisodes(data?.entries ?? []).filter(entry => opportunityLifecycle(entry) !== "research"), [data?.entries]);
  const chosen = matrix?.strategies.find(strategy => strategy.strategy_id === selected) ?? matrix?.strategies[0];
  const entered = decisions.filter(entry => entry.outcome === "entered").length;
  const unfilled = decisions.filter(entry => entry.reason_code === "entry_price_not_reached").length;
  const skipped = decisions.filter(entry => opportunityLifecycle(entry) === "stopped" && entry.reason_code !== "entry_price_not_reached").length;
  if (view === "decisions" && isLoading && !data) return <PageLoader label="Today's Decisions" />;
  return <div className="page-container space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>What the bot did and what it learned</p><h1 className="text-xl font-semibold mt-1">Decisions &amp; Research</h1></div>{view === "decisions" && <label className="text-xs" style={{ color: "var(--ink-muted)" }}>Trading day<input className="input ml-2" type="date" value={date} onChange={event => setDate(event.target.value)} /></label>}</header>
    <div className="flex gap-2"><button className={`btn ${view === "decisions" ? "btn-primary" : "btn-ghost"}`} onClick={() => setView("decisions")}>Trading decisions</button><button className={`btn ${view === "research" ? "btn-primary" : "btn-ghost"}`} onClick={() => setView("research")}>Research results</button></div>
    {view === "decisions" ? <><div className="grid grid-cols-3 gap-3">{[["Trades entered", entered, "var(--positive)"], ["Orders not filled", unfilled, "var(--warning)"], ["Setups skipped", skipped, "var(--negative)"]].map(([label, value, color]) => <div className="card p-3" key={String(label)}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold" style={{ color: String(color) }}>{String(value)}</p></div>)}</div>{error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load decisions: {(error as Error).message}</div> : decisions.length ? <div className="space-y-3">{decisions.map(entry => <DecisionCard key={entry.id} entry={entry} />)}</div> : <div className="card p-8 text-center"><SearchX size={24} className="mx-auto" /><p className="mt-2 font-medium">No setup reached the trading path on this day.</p></div>}</> : <>
      <div className="card p-4"><h2 className="font-semibold">Which ticker works with each strategy?</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Goal: PF {matrix?.target_profit_factor.toFixed(1) ?? "1.5"}. Results use saved option asks and bids, not made-up fills.</p></div>
      {matrixLoading && !matrix ? <PageLoader label="Research results" /> : matrixError ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load research: {(matrixError as Error).message}</div> : matrix && chosen ? <>
        <label className="card p-4 text-sm font-medium">Strategy<select className="select w-full mt-2" value={chosen.strategy_id} onChange={event => setSelected(event.target.value)}>{matrix.strategies.map(strategy => <option key={strategy.strategy_id} value={strategy.strategy_id}>{strategy.display_name}</option>)}</select></label>
        <div className="card p-4"><div className="flex flex-wrap justify-between gap-2"><div><h2 className="font-semibold">{chosen.display_name}</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Compared after {chosen.exit_minutes} minutes · {chosen.pairs.length} tickers</p></div>{chosen.trading_tickers.length > 0 && <span className="badge badge-green">Trades {chosen.trading_tickers.join(", ")}</span>}</div></div>
        <div className="grid gap-3 md:grid-cols-2">{chosen.pairs.map(pair => <ResearchRow key={pair.ticker} pair={pair} />)}</div>
      </> : <div className="card p-8 text-center">No research results are available yet.</div>}
    </>}
  </div>;
}
