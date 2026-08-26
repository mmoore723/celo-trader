import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FlaskConical, SearchX } from "lucide-react";
import { api, type ScannerOpportunity } from "../lib/api";
import { PageLoader } from "../components/PageLoader";
import { collapseOpportunityEpisodes, lifecycleCopy, opportunityLifecycle } from "../lib/opportunitySemantics.js";

const NAMES: Record<string, string> = {
  V2_ORB_PULLBACK: "Opening-Range Pullback", V2_SPY_TREND_CONT: "SPY Trend Continuation",
  V2_SPY_AFTERNOON_FVG: "SPY Afternoon FVG", V2_FAILED_OR_BREAK_VWAP_REVERSION: "SPY Failed-Range Recovery",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "TSLA Two-Leg Trend Pullback",
};
const todayEt = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const time = (v?: string | null) => v ? new Date(v).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) : "—";
const money = (v?: number | null) => v == null ? "—" : `$${Number(v).toFixed(2)}`;

function reason(entry: ScannerOpportunity) {
  const known: Record<string, string> = {
    entry_price_not_reached: "The order was sent, but the option never traded inside the bot's approved price range.",
    spy_afternoon_fvg_slot_reserved: "The bot saved this time slot for the higher-priority afternoon strategy.",
    daily_trade_limit_reached: "The account had already reached its trade limit for the day.",
    max_open_positions: "The account already had the maximum number of open positions.",
    cooldown_active: "The bot was waiting through its required cooldown after an earlier setup.",
  };
  return (entry.reason_code && known[entry.reason_code]) || entry.reason_detail || entry.entry_plan?.trigger || lifecycleCopy(entry).detail;
}

function decision(entry: ScannerOpportunity) {
  if (entry.outcome === "entered") return "Trade entered";
  if (entry.reason_code === "entry_price_not_reached") return "Order sent · not filled";
  return { stopped: "Skipped by a safety rule", ready: "Ready for entry", pricing: "Checking option price", watching: "Setup developing" }[opportunityLifecycle(entry)] || "Setup reviewed";
}

function DecisionCard({ entry }: { entry: ScannerOpportunity }) {
  const stage = opportunityLifecycle(entry), entered = stage === "entered", noFill = entry.reason_code === "entry_price_not_reached";
  const color = entered ? "var(--positive)" : noFill ? "var(--warning)" : stage === "stopped" ? "var(--negative)" : "var(--accent)";
  const trade = entry.trade, contract = entry.contract ?? {};
  return <article className="card p-4" style={{ borderLeft: `5px solid ${color}` }}>
    <div className="flex flex-wrap items-start gap-3">
      <div className="w-20"><p className="text-xs" style={{ color: "var(--ink-faint)" }}>{time(entry.observed_at)} ET</p><p className="text-lg font-semibold">{entry.ticker}</p></div>
      <div className="flex-1 min-w-52"><p className="text-sm font-semibold" style={{ color }}>{decision(entry)}</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{NAMES[entry.strategy_id] ?? entry.strategy_id}</p><p className="text-sm mt-2">{reason(entry)}</p></div>
      {entered && trade?.pnl != null && <div className="text-right"><p className="text-xs text-ink-muted">Result</p><p className="text-lg font-semibold" style={{ color: Number(trade.pnl) >= 0 ? "var(--positive)" : "var(--negative)" }}>{money(trade.pnl)}</p></div>}
    </div>
    <details className="mt-3 border-t pt-3" style={{ borderColor: "var(--border)" }}><summary className="text-xs font-medium cursor-pointer" style={{ color: "var(--accent)" }}>Show recorded details</summary><div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 text-xs" style={{ color: "var(--ink-muted)" }}><p><b>Direction:</b> {entry.direction || "—"}</p><p><b>Contract:</b> {trade?.contract_symbol || contract.symbol || "Not selected"}</p><p><b>Quantity:</b> {entry.planned_quantity ?? trade?.contracts ?? "—"}</p><p><b>Entry:</b> {money(trade?.entry_price ?? entry.contract_preview?.planned_entry_price ?? entry.entry_plan?.estimated_entry_price)}</p></div></details>
  </article>;
}

interface Group { key: string; ticker: string; strategy: string; count: number; completed: number; correct: number }

export function ScannerOpportunities() {
  const [view, setView] = useState<"decisions" | "research">("decisions"), [date, setDate] = useState(todayEt());
  const { data, isLoading, error } = useQuery({ queryKey: ["scanner-opportunities", date], queryFn: () => api.signals.opportunities({ date, limit: 1000 }), refetchInterval: 15_000 });
  const episodes = useMemo(() => collapseOpportunityEpisodes(data?.entries ?? []), [data?.entries]);
  const decisions = useMemo(() => episodes.filter(e => opportunityLifecycle(e) !== "research"), [episodes]);
  const research = useMemo(() => episodes.filter(e => opportunityLifecycle(e) === "research"), [episodes]);
  const groups = useMemo(() => {
    const map = new Map<string, Group>();
    for (const e of research) { const key = `${e.strategy_id}|${e.ticker}`, g = map.get(key) ?? { key, ticker: e.ticker, strategy: e.strategy_id, count: 0, completed: 0, correct: 0 }; g.count++; if (e.direction_correct != null) { g.completed++; g.correct += e.direction_correct ? 1 : 0; } map.set(key, g); }
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [research]);
  const entered = decisions.filter(e => e.outcome === "entered").length;
  const unfilled = decisions.filter(e => e.reason_code === "entry_price_not_reached").length;
  const skipped = decisions.filter(e => opportunityLifecycle(e) === "stopped" && e.reason_code !== "entry_price_not_reached").length;
  if (isLoading && !data) return <PageLoader label="Today's Decisions" />;
  return <div className="page-container space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>What the bot did and why</p><h1 className="text-xl font-semibold mt-1">Today&apos;s Decisions</h1></div><label className="text-xs" style={{ color: "var(--ink-muted)" }}>Trading day<input className="input ml-2" type="date" value={date} onChange={e => setDate(e.target.value)} /></label></header>
    <div className="flex gap-2"><button className={`btn ${view === "decisions" ? "btn-primary" : "btn-ghost"}`} onClick={() => setView("decisions")}>Trading decisions</button><button className={`btn ${view === "research" ? "btn-primary" : "btn-ghost"}`} onClick={() => setView("research")}>Strategy experiments</button></div>
    {view === "decisions" ? <><div className="grid grid-cols-3 gap-3">{[["Trades entered", entered, "var(--positive)"], ["Orders not filled", unfilled, "var(--warning)"], ["Setups skipped", skipped, "var(--negative)"]].map(([label, value, color]) => <div className="card p-3" key={String(label)}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold" style={{ color: String(color) }}>{String(value)}</p></div>)}</div>{error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load decisions: {(error as Error).message}</div> : decisions.length ? <div className="space-y-3">{decisions.map(e => <DecisionCard key={e.id} entry={e} />)}</div> : <div className="card p-8 text-center"><SearchX size={24} className="mx-auto" /><p className="mt-2 font-medium">No setup reached the trading path on this day.</p></div>}</> : <><div className="card p-4 flex gap-3"><FlaskConical size={20} style={{ color: "var(--accent)" }} /><div><p className="text-sm font-semibold">These are experiments, not missed trades.</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>The bot records how a strategy behaves on additional tickers before it is ever allowed to trade them. Repeated scanner checks are combined into one setup.</p></div></div>{groups.length ? <div className="grid gap-3 md:grid-cols-2">{groups.map(g => <article className="card p-4" key={g.key}><div className="flex justify-between gap-3"><div><p className="text-lg font-semibold">{g.ticker}</p><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{NAMES[g.strategy] ?? g.strategy}</p></div><span className="badge badge-blue">NOT TRADABLE</span></div><p className="text-sm mt-3">Testing whether this strategy also works on {g.ticker} before the bot can use real orders.</p><div className="mt-3 flex flex-wrap gap-5 text-xs" style={{ color: "var(--ink-muted)" }}><span><b>{g.count}</b> independent setups</span><span><b>{g.completed}</b> measured</span>{g.completed > 0 && <span><b>{Math.round(g.correct / g.completed * 100)}%</b> moved as expected</span>}</div></article>)}</div> : <div className="card p-8 text-center">No strategy experiments were recorded on this day.</div>}</>}
  </div>;
}
