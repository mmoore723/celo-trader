/**
 * ScannerOpportunities — the readable, day-by-day record of what the bot saw.
 *
 * Trade Journal answers "what did we actually trade?"  This page answers
 * "what did the scanner see, what was it planning, and why did it stop or
 * continue?"  They must remain separate so a blocked signal cannot be
 * mistaken for an order or a synthetic option fill.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleDollarSign, Eye, Filter, ShieldCheck } from "lucide-react";
import { api, type ScannerOpportunity } from "../lib/api";
import { PageLoader } from "../components/PageLoader";

const STRATEGY_NAMES: Record<string, string> = {
  V2_ORB_PULLBACK: "Opening-Range Pullback",
  V2_SPY_TREND_CONT: "SPY Trend Continuation", V2_SPY_AFTERNOON_FVG: "SPY Afternoon FVG",
  V2_TSLA_TWO_LEG_TREND_PULLBACK: "TSLA Two-Leg Trend Pullback",
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
function integer(value?: number | null): string { return value == null ? "Not recorded" : Number(value).toLocaleString("en-US"); }

function OutcomeBadge({ outcome }: { outcome: string }) {
  const tone = outcome === "entered" ? "badge-green" : outcome === "observed_only" ? "badge-blue" : outcome === "pending" ? "badge-yellow" : "badge-red";
  const label = outcome === "observed_only" ? "RESEARCH ONLY" : outcome === "pending" ? "UNRESOLVED" : outcome.toUpperCase();
  return <span className={`badge ${tone}`}>{label}</span>;
}

function label(value: string): string {
  const labels: Record<string, string> = {
    or_high: "Opening-range high", or_low: "Opening-range low", retest_level: "Retouch level",
    vwap: "VWAP at signal", v2_entry_reference: "Reclaim close", reference_945: "9:45 reference close", v2_stop: "Setup invalidation",
    v2_target: "Underlying objective", entry_timing: "Entry timing",
    validated_entry_rule: "Required entry rule", reviewed_paid_quote_rule: "Quote rule",
    prior_high: "Prior high", prior_low: "Prior low", impulse_extreme: "First-leg extreme", pullback_low: "Pullback low", pullback_high: "Pullback high", reclaim_level: "Reclaim level", entry_bar_high: "Signal-bar high", entry_bar_low: "Signal-bar low",
  };
  return labels[value] ?? value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function detailValue(value: string | number | boolean, key?: string): string {
  const friendly: Record<string, string> = {
    completed_1m_breakout_then_live_quote_first_retouch: "1-minute break, then first live-quote retouch",
    calls_only_first_retouch_before_1030_et: "Calls only; first retouch before 10:30 ET",
    completed_5m_signal_then_next_1m_entry: "5-minute signal, evaluated on the next 1-minute bar",
  };
  if (typeof value === "string" && key && friendly[value]) return friendly[value];
  return typeof value === "number" ? (Number.isInteger(value) ? String(value) : value.toFixed(2)) : String(value);
}

function manualChecklist(entry: ScannerOpportunity): { title: string; steps: string[] } {
  const details = entry.setup_details ?? {};
  const level = (key: string) => details[key] == null ? "the recorded level" : money(Number(details[key]));
  if (entry.strategy_id === "V2_ORB_PULLBACK") {
    return {
      title: "Manual entry checklist",
      steps: [
        `Mark the 9:30–9:45 ET opening range: high ${level("or_high")} and low ${level("or_low")}.`,
        `Wait for a completed 1-minute candle to break the range in the ${String(entry.option_type ?? "option").toUpperCase()} direction.`,
        `Do not chase the break. Watch the first return to ${level("retest_level")} and only proceed if the recorded entry rule and contract checks are satisfied.`,
      ],
    };
  }
  if (entry.strategy_id === "V2_SPY_TREND_CONT") {
    return {
      title: "Manual entry checklist",
      steps: [
        `Mark the breakout reference at ${level("v2_entry_reference")}.`,
        "Wait for the completed 5-minute trend signal; the setup is assessed on the next 1-minute bar rather than chased mid-candle.",
        `Use ${level("v2_stop")} as the underlying setup-invalidation line and ${level("v2_target")} as the underlying objective—not as option-premium stop or target prices.`,
      ],
    };
  }
  if (entry.strategy_id === "V2_TSLA_TWO_LEG_TREND_PULLBACK") {
    return {
      title: "Manual entry checklist",
      steps: [
        `After 9:45 ET, mark the reference close at ${level("reference_945")}. Price, VWAP, EMA 9, and EMA 20 must agree with the ${String(entry.option_type ?? "option").toUpperCase()} direction.`,
        `Wait for the first move to travel at least one ATR, then let price pull back toward EMA 9 without closing through VWAP. The recorded pullback level is ${level(entry.option_type === "call" ? "pullback_low" : "pullback_high")}.`,
        `Wait for a finished 1-minute candle to reclaim ${level("reclaim_level")}. The bot then evaluates the selected option on the following minute; it does not enter halfway through the candle.`,
      ],
    };
  }
  return {
    title: "Manual review checklist",
    steps: [
      "Confirm the direction and the scanner trigger shown below before considering a contract.",
      "Use the recorded underlying price and key levels; do not substitute a later market price for this historical plan.",
      "A contract can be reviewed manually only when this card says Contract selected.",
    ],
  };
}

function PlanBadge({ entry }: { entry: ScannerOpportunity }) {
  if (entry.plan_status === "contract_selected") {
    return <span className="badge badge-green"><CircleCheck size={13} /> CONTRACT SELECTED</span>;
  }
  if (entry.plan_status === "contract_preview") {
    return <span className="badge badge-yellow"><Eye size={13} /> CONTRACT TRACKED</span>;
  }
  if (entry.plan_status === "observation_only") {
    return <span className="badge badge-blue">RESEARCH OBSERVATION</span>;
  }
  return <span className="badge badge-yellow"><CircleAlert size={13} /> STOPPED BEFORE PRICING</span>;
}

function QuoteTimeline({ entry }: { entry: ScannerOpportunity }) {
  const marks = entry.option_quote_timeline ?? [];
  if (marks.length === 0) return null;
  const names: Record<string, string> = {
    entry: "Entry quote", mark_30m: "+30 min", mark_60m: "+60 min", mark_90m: "+90 min",
  };
  return <div className="mt-3 rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
    <div className="flex items-start justify-between gap-3">
      <div><p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>What happened to this exact option?</p><p className="mt-1 text-xs leading-5" style={{ color: "var(--ink-muted)" }}>Entry uses the observed ask. Later results use the price a seller could realistically hit: the bid.</p></div>
      <span className="badge badge-blue">MEASURED</span>
    </div>
    <div className="mt-3 grid grid-cols-2 gap-2">
      {marks.map((mark) => {
        const isEntry = mark.observation_kind === "entry";
        const result = mark.executable_return_pct;
        const resultColor = result == null ? "var(--ink-muted)" : result >= 0 ? "var(--positive)" : "var(--negative)";
        return <div key={mark.observation_kind} className="rounded-lg p-2.5" style={{ border: "1px solid var(--border)", background: "var(--surface-raised)" }}>
          <p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>{names[mark.observation_kind] ?? mark.observation_kind}</p>
          <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>{time(mark.observed_at)} ET · {isEntry ? `Ask ${money(mark.ask)}` : `Bid ${money(mark.bid)}`}</p>
          <p className="mt-1 text-sm font-semibold" style={{ color: resultColor }}>{isEntry ? "Starting price" : result == null ? "Quote unavailable" : `${result >= 0 ? "+" : ""}${result.toFixed(2)}%`}</p>
        </div>;
      })}
    </div>
  </div>;
}

function ContractRecipe({ entry }: { entry: ScannerOpportunity }) {
  const recipe = entry.contract_recipe;
  const selection = entry.contract_selection;
  if (!recipe) return null;
  const fields: Array<[string, string | number | undefined]> = [
    ["Contract type", recipe.option_type], ["Strike", recipe.strike_rule],
    ["Expiration", recipe.expiration_rule], ["Premium", recipe.premium_rule],
    ["Spread", recipe.spread_rule], ["Liquidity", recipe.liquidity_rule],
    ["Maximum cost", recipe.maximum_cost == null ? undefined : money(recipe.maximum_cost)],
  ];
  const selectionDetail = selection?.status === "not_selected"
    ? (selection.reason === "over_budget" && selection.cheapest_cost != null
      ? `No contract selected: the least expensive qualifying contract was ${money(selection.cheapest_cost)}${selection.cheapest_symbol ? ` (${selection.cheapest_symbol})` : ""}.`
      : selection.reason === "illiquid"
        ? `No contract selected: ${selection.illiquid_symbol || "the affordable contract"} failed ${selection.liquidity_detail || "the liquidity rule"}.`
        : `No contract selected: ${String(selection.reason || "the contract screen did not produce a qualifying choice").replace(/_/g, " ")}.`)
    : null;
  return <div className="mt-3 rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
    <p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>Contract recipe — use this to recreate the screen in E*TRADE</p>
    {recipe.recipe_source === "default_profile" && <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>The setup did not reach contract selection, so this shows the bot’s applicable contract rules—not a historical quote or chosen strike.</p>}
    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">{fields.filter(([, value]) => value != null).map(([name, value]) => <div key={name}><p style={{ color: "var(--ink-muted)" }}>{name}</p><p className="font-medium" style={{ color: "var(--ink)" }}>{value}</p></div>)}</div>
    {selectionDetail && <p className="mt-3 text-xs leading-5" style={{ color: "var(--ink-muted)" }}>{selectionDetail}</p>}
  </div>;
}

function ManualPlanCard({ entry }: { entry: ScannerOpportunity }) {
  const isCall = ["bullish", "long", "call"].includes(String(entry.direction ?? "").toLowerCase());
  const finalContract = entry.trade?.contract_symbol ? {
    symbol: entry.trade.contract_symbol, strike: entry.trade.strike, expiry: entry.trade.expiry,
  } : entry.contract;
  const preview = entry.contract_preview;
  const hasFinalContract = Boolean(finalContract?.symbol || finalContract?.strike || finalContract?.expiry);
  const hasPreview = Boolean(preview?.symbol || preview?.strike || preview?.expiry);
  const contract = hasFinalContract ? finalContract : preview;
  const hasContract = hasFinalContract || hasPreview;
  const hasMeasuredResult = entry.directional_move_pct != null;
  const chosenQuantity = entry.trade?.contracts ?? entry.planned_quantity ?? preview?.planned_contracts;
  const plannedEntry = entry.entry_plan?.estimated_entry_price ?? entry.trade?.entry_price ?? (hasFinalContract ? entry.contract?.ask : preview?.planned_entry_price ?? preview?.ask);
  const estimate = plannedEntry != null && chosenQuantity != null ? plannedEntry * chosenQuantity * 100 : null;
  const exitText = entry.exit_plan?.summary || entry.trade?.exit_reason || "The bot did not reach exit planning before this signal stopped.";
  const setupDetails = Object.entries(entry.setup_details ?? {});
  const checklist = manualChecklist(entry);
  const underlyingEntry = entry.entry_plan?.underlying_price ?? entry.underlying_entry_price;
  const underlyingStop = entry.setup_details?.v2_stop ?? entry.setup_details?.setup_invalidation ?? entry.setup_details?.or_low;
  const underlyingTarget = entry.setup_details?.v2_target ?? entry.setup_details?.underlying_objective;
  const potentialMove = typeof underlyingEntry === "number" && typeof underlyingTarget === "number"
    ? Math.abs(underlyingTarget - underlyingEntry) : null;
  const stopExplanation = underlyingStop == null
    ? "No fixed underlying stop was recorded; follow the exit rule below."
    : money(Number(underlyingStop));
  const targetExplanation = underlyingTarget == null
    ? "Time/structure exit"
    : money(Number(underlyingTarget));
  const decisionTitle = entry.outcome === "entered" ? "ENTERED"
    : entry.outcome === "blocked" ? "STOPPED"
      : entry.outcome === "observed_only" ? "RESEARCH ONLY" : "WAITING";
  const decisionExplanation = entry.reason_detail
    || (entry.outcome === "entered" ? "The bot completed the setup, contract, sizing, and entry checks."
      : entry.outcome === "observed_only" ? "This setup was recorded for research and was not authorized to place an order."
        : "The setup has not produced a final routing decision yet.");
  return (
    <article className="card overflow-hidden" style={{ borderLeft: "6px solid var(--accent)" }}>
      <header className="px-5 py-4 flex flex-wrap items-start gap-3" style={{ background: "linear-gradient(135deg, #172033 0%, #242d42 100%)", borderBottom: "1px solid var(--border)" }}>
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "#70d1c7" }}>Celo trade play sheet</p>
          <p className="mt-1 text-xl font-semibold text-white">{entry.ticker} {isCall ? "Bullish" : "Bearish"} {STRATEGY_NAMES[entry.strategy_id] ?? entry.strategy_id}</p>
          <p className="text-xs mt-1" style={{ color: "#cbd5e1" }}>Detected {time(entry.observed_at)} ET · Trigger bar {time(entry.trigger_bar)} · {Math.round(entry.confidence * 100)}% setup confidence</p>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2"><PlanBadge entry={entry} /><OutcomeBadge outcome={entry.outcome} /></div>
      </header>
      <div className="px-5 py-5" style={{ background: "var(--surface-raised)", borderBottom: "1px solid var(--border)" }}>
        <div className="grid gap-5 lg:grid-cols-[1fr_1.15fr]">
          <section>
            <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Underlying trade idea</p>
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-x-5 gap-y-4">
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Symbol</p><p className="text-lg font-semibold" style={{ color: "var(--ink)" }}>{entry.ticker}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Entry trigger</p><p className="text-lg font-semibold" style={{ color: "var(--ink)" }}>{money(underlyingEntry)}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Position</p><p className="text-lg font-semibold" style={{ color: isCall ? "var(--positive)" : "var(--negative)" }}>{isCall ? "CALL / Long" : "PUT / Short"}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Target</p><p className="font-semibold" style={{ color: "var(--positive)" }}>{targetExplanation}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Stop / invalidation</p><p className="font-semibold" style={{ color: underlyingStop == null ? "var(--ink)" : "var(--negative)" }}>{stopExplanation}</p></div>
              <div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Potential underlying move</p><p className="font-semibold" style={{ color: "var(--ink)" }}>{potentialMove == null ? "Rule-based exit" : money(potentialMove)}</p></div>
            </div>
            <div className="mt-4 rounded-lg px-3 py-3" style={{ background: entry.outcome === "blocked" ? "var(--negative-bg)" : "var(--surface)", border: "1px solid var(--border)" }}>
              <p className="text-xs font-semibold" style={{ color: entry.outcome === "blocked" ? "var(--negative)" : "var(--ink)" }}>{decisionTitle}: why the bot did or did not enter</p>
              <p className="mt-1 text-sm leading-5" style={{ color: "var(--ink)" }}>{decisionExplanation}</p>
            </div>
          </section>
          <section className="rounded-xl p-4" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
            <div className="flex items-center justify-between gap-2"><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Suggested option contract</p><span className="text-xs" style={{ color: "var(--ink-muted)" }}>{hasContract ? "Recorded at signal time" : "Not selected"}</span></div>
            {hasContract && contract ? <>
              <p className="mt-2 text-base font-semibold break-all" style={{ color: "var(--accent)" }}>{contract.symbol || `${entry.ticker} ${entry.option_type?.toUpperCase()} ${contract.strike ?? ""}`}</p>
              <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3 text-sm">
                <div><p style={{ color: "var(--ink-muted)" }}>Type</p><strong>{entry.option_type?.toUpperCase() || "OPTION"}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Expiration</p><strong>{contract.expiry || "Not recorded"}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Strike</p><strong>{contract.strike == null ? "Not recorded" : money(contract.strike)}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Quantity</p><strong>{chosenQuantity ?? "Not sized"}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Bid</p><strong>{money(contract.bid)}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Ask</p><strong>{money(contract.ask)}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Volume</p><strong>{integer(contract.volume)}</strong></div>
                <div><p style={{ color: "var(--ink-muted)" }}>Open interest</p><strong>{integer(contract.open_interest)}</strong></div>
              </div>
              <div className="mt-4 pt-3 grid grid-cols-2 gap-4" style={{ borderTop: "1px solid var(--border)" }}><div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Planned option entry</p><p className="text-lg font-semibold">{money(plannedEntry)}</p></div><div><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Estimated total cost</p><p className="text-lg font-semibold">{money(estimate ?? preview?.estimated_position_cost)}</p></div></div>
            </> : <div className="mt-3 rounded-lg p-3" style={{ background: "var(--warning-bg)" }}><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>No contract was selected.</p><p className="mt-1 text-xs leading-5" style={{ color: "var(--ink-muted)" }}>{entry.contract_selection?.reason ? `Contract screen stopped at: ${entry.contract_selection.reason.replace(/_/g, " ")}.` : "The setup stopped before a real strike and quote were recorded. The bot will never fabricate these fields."}</p></div>}
          </section>
        </div>
        <div className="mt-4 rounded-lg px-4 py-3" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface))", border: "1px solid var(--border)" }}><p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>Exit plan</p><p className="mt-1 text-sm" style={{ color: "var(--ink)" }}>{exitText}</p></div>
      </div>
      <details className="px-5 py-4" style={{ borderBottom: "1px solid var(--border)" }}>
        <summary className="cursor-pointer text-sm font-semibold" style={{ color: "var(--accent)" }}>How to recognize and repeat this setup</summary>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <section className="rounded-xl p-4" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{checklist.title}</p>
            <p className="mt-2 text-sm leading-6" style={{ color: "var(--ink)" }}>{entry.entry_plan?.trigger || "Scanner setup detected"}</p>
            <ol className="mt-3 space-y-2 text-sm leading-5" style={{ color: "var(--ink-muted)" }}>{checklist.steps.map((step, index) => <li key={step} className="flex gap-2"><strong style={{ color: "var(--accent)" }}>{index + 1}.</strong><span>{step}</span></li>)}</ol>
          </section>
          <section className="rounded-xl p-4" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Recorded chart levels</p>
            {setupDetails.length > 0 ? <div className="mt-3 grid grid-cols-2 gap-3">{setupDetails.map(([key, value]) => <div key={key}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label(key)}</p><p className="text-sm font-medium" style={{ color: "var(--ink)" }}>{detailValue(value, key)}</p></div>)}</div> : <p className="mt-2 text-sm" style={{ color: "var(--ink-muted)" }}>No additional chart levels were recorded for this historical detection.</p>}
            <ContractRecipe entry={entry} />
          </section>
        </div>
      </details>
      <div className="px-5 py-4 grid gap-4 md:grid-cols-2">
        <section>
          <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--accent)" }}>What happened afterward</p>
          {entry.trade?.status ? <p className="mt-2 text-sm" style={{ color: "var(--ink-muted)" }}>Actual trade: <strong style={{ color: "var(--ink)" }}>{entry.trade.status}</strong> · Exit {money(entry.trade.exit_price)} · P&amp;L {entry.trade.pnl == null ? "—" : money(entry.trade.pnl)}</p>
            : hasMeasuredResult ? <p className="mt-2 text-sm" style={{ color: entry.direction_correct ? "var(--positive)" : "var(--negative)" }}>60-minute underlying move: {percent(entry.directional_move_pct)} {entry.direction_correct ? "with" : "against"} the setup</p>
            : <p className="mt-2 text-sm" style={{ color: "var(--ink-muted)" }}>The later result is still being measured.</p>}
        </section>
        <QuoteTimeline entry={entry} />
      </div>
      <footer className="px-4 py-3 text-xs flex gap-2 items-start" style={{ borderTop: "1px solid var(--border)", color: "var(--ink-muted)" }}><CircleDollarSign size={15} className="shrink-0" />This is the bot's recorded plan at that moment—not a new order or a recommendation. Copy only a <strong style={{ color: "var(--ink)" }}>Contract selected</strong> plan if you are reviewing it manually.</footer>
    </article>
  );
}

export function ScannerOpportunities() {
  const [date, setDate] = useState(todayEt());
  const [outcome, setOutcome] = useState("all");
  const [ticker, setTicker] = useState("all");
  const [strategy, setStrategy] = useState("all");
  const { data, isLoading, error } = useQuery({
    queryKey: ["scanner-opportunities", date, outcome, ticker, strategy],
    queryFn: () => api.signals.opportunities({ date, outcome: outcome === "all" ? undefined : outcome, ticker: ticker === "all" ? undefined : ticker, strategy: strategy === "all" ? undefined : strategy }),
    refetchInterval: 15_000,
  });
  const { data: gateScorecard } = useQuery({
    queryKey: ["gate-calibration", 30], queryFn: () => api.signals.gateScorecard(30), staleTime: 60_000,
  });
  const entries = data?.entries ?? [];
  const tickers = useMemo(() => Array.from(new Set(entries.map((entry) => entry.ticker))).sort(), [entries]);
  const strategies = useMemo(() => Array.from(new Set(entries.map((entry) => entry.strategy_id))).sort(), [entries]);
  if (isLoading && !data) return <PageLoader label="Scanner Opportunities" />;
  return <div className="page-container space-y-4">
    <header>
      <p className="text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--accent)" }}>Scanner audit trail</p>
      <h1 className="text-xl font-semibold mt-1" style={{ color: "var(--ink)" }}>Scanner Opportunities</h1>
      <p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Every strategy detection, separated into research observations and decisions that actually reached the trade router.</p>
    </header>
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
      {[["DETECTIONS", data?.summary.total ?? 0, "var(--ink)"], ["ROUTED", data?.summary.routed ?? 0, "var(--ink)"], ["ENTERED", data?.summary.entered ?? 0, "var(--positive)"], ["BLOCKED", data?.summary.blocked ?? 0, "var(--negative)"], ["RESEARCH ONLY", data?.summary.research_only ?? data?.summary.observed_only ?? 0, "var(--accent)"], ["UNRESOLVED", data?.summary.unresolved ?? data?.summary.pending ?? 0, "var(--warning)"]].map(([label, value, color]) => <div key={String(label)} className="card p-3"><p className="text-xs" style={{ color: "var(--ink-muted)" }}>{label}</p><p className="text-2xl font-semibold mt-1" style={{ color: String(color) }}>{String(value)}</p></div>)}
    </div>
    <div className="card p-3 flex flex-wrap items-end gap-3">
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Trading day<input type="date" value={date} onChange={(event) => setDate(event.target.value)} className="input mt-1 block" /></label>
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Outcome<select value={outcome} onChange={(event) => setOutcome(event.target.value)} className="input mt-1 block"><option value="all">All outcomes</option><option value="entered">Entered</option><option value="blocked">Blocked</option><option value="observed_only">Research only</option><option value="pending">Unresolved</option></select></label>
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Ticker<select value={ticker} onChange={(event) => setTicker(event.target.value)} className="input mt-1 block"><option value="all">All tickers</option>{tickers.map((value) => <option key={value}>{value}</option>)}</select></label>
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>Strategy<select value={strategy} onChange={(event) => setStrategy(event.target.value)} className="input mt-1 block"><option value="all">All strategies</option>{strategies.map((value) => <option key={value}>{STRATEGY_NAMES[value] ?? value}</option>)}</select></label>
      <div className="ml-auto text-xs flex items-center gap-1" style={{ color: "var(--ink-muted)" }}><Eye size={14} /> {data?.account_scoped ? "This broker account" : "Legacy records only"}</div>
    </div>
    <p className="text-xs" style={{ color: "var(--ink-muted)" }}><ShieldCheck size={13} style={{ display: "inline", marginRight: 5 }} />{data?.note}</p>
    {(gateScorecard?.rows.length ?? 0) > 0 && <section className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Are the decision gates helping?</h2><p className="mt-1 text-xs leading-5" style={{ color: "var(--ink-muted)" }}>A saved loser helps. A rejected winner hurts. Results are kept separate for every strategy because a gate can help one setup and damage another.</p></div>
        <span className="badge badge-yellow">30-DAY CALIBRATION</span>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {gateScorecard!.rows.map((row) => <div key={`${row.strategy_id}-${row.gate}`} className="rounded-xl p-3" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
          <div className="flex items-center justify-between gap-2"><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{STRATEGY_NAMES[row.strategy_id] ?? row.strategy_id}</p><div className="flex gap-1"><span className={`badge ${row.enforced ? "badge-green" : "badge-blue"}`}>{row.enforced ? "ACTIVE GATE" : "OBSERVATION ONLY"}</span><span className={`badge ${row.validation?.recommended_for_enforcement ? "badge-green" : row.status === "failed_chronological_validation" ? "badge-red" : "badge-yellow"}`}>{row.validation?.recommended_for_enforcement ? "PASSED LATER DATA" : row.status === "failed_chronological_validation" ? "DID NOT IMPROVE" : "LEARNING"}</span></div></div>
          <p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>{row.gate === "ai_decision_veto" ? "AI decision review" : "Market/VWAP alignment"} · {row.independent_episodes} distinct setup episode{row.independent_episodes === 1 ? "" : "s"} across {row.trading_days} day{row.trading_days === 1 ? "" : "s"}</p>
          <div className="mt-3 grid grid-cols-3 gap-2"><div className="rounded-lg p-2" style={{ background: "var(--positive-bg)" }}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Losers avoided</p><p className="text-lg font-semibold" style={{ color: "var(--positive)" }}>{row.avoided_losers}</p></div><div className="rounded-lg p-2" style={{ background: "var(--negative-bg)" }}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Winners rejected</p><p className="text-lg font-semibold" style={{ color: "var(--negative)" }}>{row.rejected_winners}</p></div><div className="rounded-lg p-2" style={{ background: "var(--surface)" }}><p className="text-xs" style={{ color: "var(--ink-muted)" }}>AI-approved win rate</p><p className="text-lg font-semibold" style={{ color: "var(--ink)" }}>{row.allowed.win_rate_pct == null ? "—" : `${row.allowed.win_rate_pct}%`}</p></div></div>
          {row.validation?.training && row.validation?.holdout && <div className="mt-3 grid grid-cols-2 gap-2">
            {[['Earlier data', row.validation.training], ['Later unseen data', row.validation.holdout]].map(([label, period]) => {
              const metrics = period as NonNullable<typeof row.validation>['training'];
              return <div key={String(label)} className="rounded-lg p-2" style={{ background: "var(--surface)" }}><p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>{String(label)}</p><p className="mt-1 text-xs" style={{ color: "var(--ink-muted)" }}>Strategy alone: {metrics?.baseline_avg_return_pct?.toFixed(2) ?? '—'}% avg</p><p className="text-xs" style={{ color: (metrics?.incremental_avg_return_pct ?? 0) > 0 ? "var(--positive)" : "var(--negative)" }}>With AI: {metrics?.ai_policy_avg_return_pct?.toFixed(2) ?? '—'}% avg · change {metrics?.incremental_avg_return_pct == null ? '—' : `${metrics.incremental_avg_return_pct > 0 ? '+' : ''}${metrics.incremental_avg_return_pct.toFixed(2)}%`}</p></div>;
            })}
          </div>}
          <p className="mt-2 text-xs" style={{ color: "var(--ink-muted)" }}>Independent option outcomes: {row.validation?.option_episodes ?? 0}/{row.validation?.minimum_evidence.option_episodes ?? 60} · AI vetoes: {row.validation?.veto_episodes ?? row.measured}/{row.validation?.minimum_evidence.veto_episodes ?? 12} · AI approvals: {row.validation?.approval_episodes ?? row.allowed.measured}/{row.validation?.minimum_evidence.approval_episodes ?? 12} · Trading days: {row.validation?.trading_days ?? row.trading_days}/{row.validation?.minimum_evidence.trading_days ?? 20} · Raw one-minute reviews: {row.raw_decisions} · Delayed inside the same setup: {row.delayed_then_allowed}</p>
        </div>)}
      </div>
      <p className="mt-3 text-xs" style={{ color: "var(--ink-muted)" }}>{gateScorecard?.policy}</p>
    </section>}
    {error ? <div className="card p-4" style={{ color: "var(--negative)" }}>Could not load scanner opportunities: {(error as Error).message}</div> : entries.length === 0 ? <div className="card p-8 text-center"><Filter size={24} style={{ margin: "0 auto", color: "var(--ink-faint)" }} /><p className="mt-2 font-medium" style={{ color: "var(--ink)" }}>No recorded setups for this day</p><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Choose another trading day, or let the scanner run to begin building its audit trail.</p></div> : <div className="space-y-4">{entries.map((entry) => <ManualPlanCard key={entry.id} entry={entry} />)}</div>}
  </div>;
}
