import type { DailyEvidenceScorecard } from "../lib/api";

function valueOrDash(value: number | string | null, suffix = "") {
  return value === null ? "—" : `${value}${suffix}`;
}

export function DailyEvidencePanel({ data, loading = false, failed = false }: {
  data?: DailyEvidenceScorecard;
  loading?: boolean;
  failed?: boolean;
}) {
  if (!data && (loading || !failed)) {
    return (
      <div className="card p-4 text-xs" style={{ color: "var(--ink-muted)" }}>
        Loading today&apos;s evidence…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="card p-4 text-xs" style={{ color: "var(--negative)" }}>
        Today&apos;s evidence could not load. The page will retry automatically.
      </div>
    );
  }
  if (!data.account_scoped) {
    return (
      <div className="card p-4 text-xs" style={{ color: "var(--ink-muted)" }}>
        Connect the active brokerage account to build an account-isolated daily review.
      </div>
    );
  }
  const pf = data.trading.profit_factor === "infinite"
    ? "No losses"
    : valueOrDash(data.trading.profit_factor);
  const replayColor = data.replay.coverage_pct === 100 ? "var(--positive)" : "#ffd740";
  const stats = [
    { label: "Profit factor", value: pf, note: "gross wins ÷ gross losses" },
    { label: "Signal accuracy", value: valueOrDash(data.decisions.directional_accuracy_pct, "%"), note: `${data.decisions.measured} measured candidates` },
    { label: "Entry fills", value: valueOrDash(data.execution.entry_fill_rate_pct, "%"), note: `${data.execution.entry_filled}/${data.execution.entry_attempts} attempts` },
    { label: "Replay coverage", value: `${data.replay.coverage_pct}%`, note: data.replay.passed ? "evidence linked" : "links need review", color: replayColor },
  ];
  const missed = data.decisions.missed_executable_moves["planned_hold"];
  const fillLeakage = data.execution.quote_to_fill;
  const quoteReplay = data.execution.tradier_quote_replay;
  const fillLeakageDollars = fillLeakage?.signed_adverse_slippage_dollars;
  const fillLeakageAmount = fillLeakageDollars === null || fillLeakageDollars === undefined
    ? null
    : `${fillLeakageDollars > 0 ? "+" : fillLeakageDollars < 0 ? "-" : ""}$${Math.abs(fillLeakageDollars).toFixed(2)}`;
  const fillLeakageComparison = fillLeakageDollars === null || fillLeakageDollars === undefined
    ? ""
    : fillLeakageDollars > 0 ? "worse than" : fillLeakageDollars < 0 ? "better than" : "matching";
  return (
    <div className="card p-4 flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>What the evidence says</h3>
        <p className="text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
          Profit, decision quality, order execution, and record completeness are scored separately.
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {stats.map(stat => (
          <div key={stat.label} className="rounded-md px-3 py-2" style={{ background: "var(--muted)" }}>
            <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>{stat.label}</p>
            <p className="num text-base font-bold" style={{ color: stat.color ?? "var(--ink)" }}>{stat.value}</p>
            <p className="text-[10px]" style={{ color: "var(--ink-muted)" }}>{stat.note}</p>
          </div>
        ))}
      </div>
      {missed?.measured > 0 && (
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Missed-order quote replay: <strong>{missed.profitable}/{missed.measured}</strong> positive at each strategy's planned hold
          {missed.estimated_pnl_dollars !== null && missed.estimated_pnl_dollars !== undefined
            ? `, estimated ${missed.estimated_pnl_dollars >= 0 ? "+" : "-"}$${Math.abs(missed.estimated_pnl_dollars).toFixed(2)} before fees.`
            : "."}{" "}
          Recorded ask-to-bid quotes only; these are not guaranteed fills or profit.
        </p>
      )}
      {quoteReplay?.measured_trades > 0 && quoteReplay.quote_pnl_after_fees !== null && (
        <div className="rounded-md px-3 py-2" style={{ background: "var(--muted)" }}>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
            Tradier reality check: <strong style={{ color: quoteReplay.quote_pnl_after_fees >= 0 ? "var(--positive)" : "var(--negative)" }}>
              {quoteReplay.quote_pnl_after_fees >= 0 ? "+" : "-"}${Math.abs(quoteReplay.quote_pnl_after_fees).toFixed(2)}
            </strong>{" "}
            after modeled fees, using the saved ask to enter and bid to exit. PF {quoteReplay.quote_profit_factor_after_fees === null ? "—" : quoteReplay.quote_profit_factor_after_fees.toFixed(2)} across {quoteReplay.measured_trades} trade{quoteReplay.measured_trades === 1 ? "" : "s"}.
          </p>
          <p className="text-[10px] mt-1" style={{ color: "var(--ink-faint)" }}>
            {quoteReplay.exact_exit_quotes} exact exit quote{quoteReplay.exact_exit_quotes === 1 ? "" : "s"}; {quoteReplay.legacy_nearby_marks} older nearby estimate{quoteReplay.legacy_nearby_marks === 1 ? "" : "s"}. Quote replay is not a guaranteed broker fill.
          </p>
        </div>
      )}
      {fillLeakage?.paired_fills > 0 && fillLeakageAmount !== null && (
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Broker fill leakage: <strong style={{ color: fillLeakageDollars !== undefined && fillLeakageDollars !== null && fillLeakageDollars > 0 ? "var(--warning)" : "var(--positive)" }}>
            {fillLeakageAmount}
          </strong>{" "}
          {fillLeakageComparison} the saved Tradier quote across {fillLeakage.paired_fills} confirmed fill{fillLeakage.paired_fills === 1 ? "" : "s"}.
        </p>
      )}
      <ul className="text-xs pl-4 list-disc" style={{ color: "var(--ink-muted)" }}>
        {data.observations.map((text, index) => <li key={`${index}-${text}`}>{text}</li>)}
      </ul>
      <p className="text-[10px]" style={{ color: "var(--ink-faint)" }}>{data.launch_readiness.note}</p>
    </div>
  );
}
