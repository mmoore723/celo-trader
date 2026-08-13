/**
 * ScannerOpportunities — the readable, day-by-day record of what the bot saw.
 *
 * Trade Journal answers "what did we actually trade?"  This page answers
 * "what did the scanner see, what was it planning, and why did it stop or
 * continue?"  They must remain separate so a blocked signal cannot be
 * mistaken for an order or a synthetic option fill.
 */
import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Eye, Filter, ShieldCheck } from "lucide-react";
import { api, type ScannerOpportunity } from "../lib/api";
import { PageLoader } from "../components/PageLoader";

const STRATEGY_NAMES: Record<string, string> = {
  V2_ORB_PULLBACK: "Opening-Range Pullback", V2_TREND_CONT: "Trend Continuation",
  V2_SPY_TREND_CONT: "SPY Trend Continuation", V2_SPY_AFTERNOON_FVG: "SPY Afternoon FVG",
  V2_SPY_AFTERNOON_REVERSAL: "SPY Afternoon Reversal", V2_TSLA_NOISE_MOMENTUM: "TSLA Noise Momentum",
  TREND_CONT: "Trend Continuation", INST_ORB: "Opening-Range Breakout", MID_BRK: "Mid-Day Breakdown",
  VWAP_PB: "VWAP Pullback", FVG: "Fair Value Gap", AFT_REV: "Afternoon Reversal", LIQ_SWEEP: "Liquidity Sweep",
};

function todayEt(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date());
}
function time(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
}
function money(value?: number | null): string { return value == null ? "—" : `$${Number(value).toFixed(2)}`; }
function percent(value?: number | null): string { return value == null ? "Waiting" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`; }

function OutcomeBadge({ outcome }: { outcome: string }) {
  const tone = outcome === "entered" ? "badge-green" : outcome === "observed_only" ? "badge-blue" : outcome === "pending" ? "badge-yellow" : "badge-red";
  const label = outcome === "observed_only" ? "OBSERVED" : outcome.toUpperCase();
  return <span className={`badge ${tone}`}>{label}</span>;
}

function OpportunityDetail({ entry }: { entry: ScannerOpportunity }) {
  const contract = entry.trade?.contract_symbol ? {
    symbol: entry.trade.contract_symbol, strike: entry.trade.strike, expiry: entry.trade.expiry,
  } : entry.contract;
  const hasContract = Boolean(contract?.symbol || contract?.strike || contract?.expiry);
  const hasMeasuredResult = entry.directional_move_pct != null;
  const chosenQuantity = entry.trade?.contracts ?? entry.planned_quantity;
  const exitText = entry.trade?.exit_reason || entry.exit_plan?.summary || "The bot did not reach exit planning before this signal stopped.";
  return (
    <tr>
      <td colSpan={8} style={{ padding: 0 }}>
        <div className="px-5 py-4 grid gap-3 md:grid-cols-3" style={{ background: "var(--surface-raised)", borderBottom: "1px solid var(--border)" }}>
          <section>
            <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>1. Entry idea</p>
            <p className="mt-1 text-sm" style={{ color: "var(--ink)" }}>{entry.entry_plan?.trigger || "Scanner setup detected"}</p>
            <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>Underlying when checked: {money(entry.entry_plan?.underlying_price ?? entry.underlying_entry_price)}</p>
          </section>
          <section>
            <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>2. Contract & size</p>
            {hasContract ? <>
              <p className="mt-1 text-sm font-medium" style={{ color: "var(--ink)" }}>{contract.symbol || `${entry.ticker} ${contract.strike ?? ""}`}</p>
              <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>Strike {contract.strike ?? "—"} · Exp. {contract.expiry || "—"} · {chosenQuantity ?? "—"} contract{chosenQuantity === 1 ? "" : "s"}</p>
              <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>Estimated entry {money(entry.entry_plan?.estimated_entry_price ?? entry.trade?.entry_price ?? entry.contract?.ask)}</p>
            </> : <p className="mt-1 text-sm" style={{ color: "var(--ink-muted)" }}>Not priced. A gate stopped this setup before the bot selected a contract.</p>}
          </section>
          <section>
            <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>3. Exit plan & later result</p>
            <p className="mt-1 text-sm" style={{ color: "var(--ink)" }}>{exitText}</p>
            {entry.trade?.status ? <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>Actual trade: {entry.trade.status} · P&L {entry.trade.pnl == null ? "—" : money(entry.trade.pnl)}</p>
              : hasMeasuredResult ? <p className="mt-1 text-xs" style={{ color: entry.direction_correct ? "var(--positive)" : "var(--negative)" }}>60-minute underlying move: {percent(entry.directional_move_pct)} {entry.direction_correct ? "in the signal direction" : "against the signal direction"}</p>
              : <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>Later outcome is still being measured.</p>}
          </section>
          {entry.reason_detail && <p className="md:col-span-3 text-xs rounded-lg px-3 py-2" style={{ background: "var(--surface)", color: "var(--ink-muted)" }}><strong style={{ color: "var(--ink)" }}>Why it stopped:</strong> {entry.reason_detail}</p>}
        </div>
      </td>
    </tr>
  );
}

export function ScannerOpportunities() {
  const [date, setDate] = useState(todayEt());
  const [outcome, setOutcome] = useState("all");
  const [ticker, setTicker] = useState("all");
  const [strategy, setStrategy] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["scanner-opportunities", date, outcome, ticker, strategy],
    queryFn: () => api.signals.opportunities({ date, outcome: outcome === "all" ? undefined : outcome, ticker: ticker === "all" ? undefined : ticker, strategy: strategy === "all" ? undefined : strategy }),
    refetchInterval: 15_000,
  });
  const entries = data?.entries ?? [];
  const tickers = useMemo(() => Array.from(new Set(entries.map((entry) => entry.ticker))).sort(), [entries]);
  const strategies = useMemo(() => Array.from(new Set(entries.map((entry) => entry.strategy_id))).sort(), [entries]);
  if (isLoading && !data) return <PageLoader label="Scanner Opportunities" />;
  return <div className="page-container space-y-4">
    <header>
      <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>Scanner audit trail</p>
      <h1 className="text-xl font-semibold mt-1" style={{ color: "var(--ink)" }}>Scanner Opportunities</h1>
      <p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Every real setup the scanner found—whether the bot entered it, stopped it, or observed it for research.</p>
    </header>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[["SETUPS", data?.summary.total ?? 0, "var(--ink)"], ["ENTERED", data?.summary.entered ?? 0, "var(--positive)"], ["BLOCKED", data?.summary.blocked ?? 0, "var(--negative)"], ["OBSERVED", data?.summary.observed_only ?? 0, "var(--accent)"]].map(([label, value, color]) => <div key={String(label)} className="card p-3"><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold mt-1" style={{ color: String(color) }}>{String(value)}</p></div>)}
    </div>
    <div className="card p-3 flex flex-wrap items-end gap-3">
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Trading day<input type="date" value={date} onChange={(event) => { setDate(event.target.value); setExpanded(null); }} className="input mt-1 block" /></label>
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value)} className="input mt-1 block"><option value="all">All outcomes</option><option value="entered">Entered</option><option value="blocked">Blocked</option><option value="observed_only">Observed only</option><option value="pending">Waiting for result</option></select></label>
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Ticker<select value={ticker} onChange={(event) => setTicker(event.target.value)} className="input mt-1 block"><option value="all">All tickers</option>{tickers.map((value) => <option key={value}>{value}</option>)}</select></label>
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Strategy<select value={strategy} onChange={(event) => setStrategy(event.target.value)} className="input mt-1 block"><option value="all">All strategies</option>{strategies.map((value) => <option key={value}>{STRATEGY_NAMES[value] ?? value}</option>)}</select></label>
      <div className="ml-auto text-xs flex items-center gap-1" style={{ color: "var(--ink-muted)" }}><Eye size={14} /> {data?.account_scoped ? "This broker account" : "Legacy records only"}</div>
    </div>
    <p className="text-xs" style={{ color: "var(--ink-muted)" }}><ShieldCheck size={13} style={{ display: "inline", marginRight: 5 }} />{data?.note}</p>
    {error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load scanner opportunities: {(error as Error).message}</div> : entries.length === 0 ? <div className="card p-8 text-center"><Filter size={24} style={{ margin: "0 auto", color: "var(--ink-faint)" }} /><p className="mt-2 font-medium" style={{ color: "var(--ink)" }}>No recorded setups for this day</p><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Choose another trading day, or let the scanner run to begin building its audit trail.</p></div> : <div className="card overflow-x-auto"><table className="w-full text-sm"><thead><tr style={{ background: "var(--surface-raised)", color: "var(--ink-muted)" }}><th className="p-3 text-left">Time</th><th className="p-3 text-left">Setup</th><th className="p-3 text-left">Direction</th><th className="p-3 text-left">Decision</th><th className="p-3 text-left">Why</th><th className="p-3 text-right">Later move</th><th className="p-3 text-right">Plan</th><th className="p-3" /></tr></thead><tbody>{entries.map((entry) => <Fragment key={entry.id}><tr className="border-t" style={{ borderColor: "var(--border)" }}><td className="p-3 whitespace-nowrap">{time(entry.observed_at)}</td><td className="p-3"><strong>{entry.ticker}</strong><span className="block text-xs" style={{ color: "var(--ink-muted)" }}>{STRATEGY_NAMES[entry.strategy_id] ?? entry.strategy_id}</span></td><td className="p-3"><span style={{ color: entry.direction === "bullish" ? "var(--positive)" : "var(--negative)" }}>{entry.direction === "bullish" ? "CALL idea" : "PUT idea"}</span><span className="block text-xs" style={{ color: "var(--ink-muted)" }}>{Math.round(entry.confidence * 100)}% confidence</span></td><td className="p-3"><OutcomeBadge outcome={entry.outcome} /></td><td className="p-3 text-xs" style={{ color: "var(--ink-muted)" }}>{entry.reason_detail || (entry.outcome === "entered" ? "All gates cleared" : entry.outcome === "observed_only" ? "Paper observation only" : "Still evaluating")}</td><td className="p-3 text-right" style={{ color: entry.directional_move_pct == null ? "var(--ink-muted)" : entry.direction_correct ? "var(--positive)" : "var(--negative)" }}>{percent(entry.directional_move_pct)}</td><td className="p-3 text-right text-xs" style={{ color: "var(--ink-muted)" }}>{entry.planned_quantity ? `${entry.planned_quantity} contract${entry.planned_quantity === 1 ? "" : "s"}` : "Details"}</td><td className="p-3 text-right"><button className="btn btn-ghost btn-sm" onClick={() => setExpanded(expanded === entry.id ? null : entry.id)} aria-expanded={expanded === entry.id}>{expanded === entry.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<span className="sr-only">{expanded === entry.id ? "Hide" : "Show"} details</span></button></td></tr>{expanded === entry.id && <OpportunityDetail entry={entry} />}</Fragment>)}</tbody></table></div>}
  </div>;
}
