import type { StrategyTickerResearchPair } from "../lib/api";
import { researchProfitFactorText } from "../lib/researchPairView.js";

const money = (n: number | null) => n == null ? "—" : `$${n.toFixed(2)}`;
export function ProfitProtectionComparison({ comparison: c, reference = false }: { comparison: StrategyTickerResearchPair["profit_protection_comparison"]; reference?: boolean }) {
  if (!c) return null;
  const recovery = c.protocol === "recovery_vwap_then_option_3spread_2spread_30m_v1";
  const minutes = c.minutes ?? 30;
  return <div className="rounded-lg px-3 py-2" style={{ background: "var(--surface-sunken)", color: "var(--ink-muted)" }}>
    <b style={{ color: "var(--ink)" }}>{recovery ? "Recovery profit protection test" : "Profit protection test"}</b> · {reference ? "7–21-day" : "0–7-day"} options · {c.paired_results} matched plays · {c.paired_days} days
    {c.paired_results > 0 ? <p>{minutes}-minute exit PF {researchProfitFactorText(c.control.profit_factor, c.paired_results)} → Option trail PF {researchProfitFactorText(c.trail.profit_factor, c.paired_results)} · Average change {money(c.average_improvement)} per contract</p>
      : <p>No matched results yet. Testing whether an option-price trail keeps more profit.</p>}
    <details className="mt-1"><summary className="cursor-pointer">Test rules and missing data</summary>
      <p>Same play, option, and entry ask. Both exit by {minutes} minutes. Research only; trading rules stay unchanged.</p>
      {recovery && <p>{c.target_reached ?? 0} plays reached the recovery target. The option trail can arm only after a full candle closes past that target; reaching it does not sell the position.</p>}
      <p>The trail starts after the option gains its modeled costs plus 3 entry spreads. It follows 2 spreads behind the best observed bid and never moves backward.</p>
      <p>{c.unpaired} of {c.tracked} plays not yet comparable · {c.statuses.missing_path ?? 0} incomplete price paths · {c.statuses.missing_quote ?? 0} missing exit prices</p>
      {c.paired_results > 0 && <p>After-cost P&amp;L: {minutes}-minute {money(c.control.net_pnl)} · Trail {money(c.trail.net_pnl)} · Typical change {money(c.median_improvement)}</p>}
      <p>Sampled quotes can miss brief moves. These are modeled research results, not broker fills or permission to trade.</p>
    </details>
    {c.initial_loss_comparison && <details className="mt-2">
      <summary className="cursor-pointer font-medium" style={{color: "var(--ink)"}}>Compare four exits · {c.initial_loss_comparison.paired_results} matched plays</summary>
      <p className="mt-1">Same entries and options. Testing a 20% option-price loss limit—not a guaranteed loss cap.</p>
      <table className="w-full mt-2 text-left">
        <thead><tr><th scope="col">Exit</th><th scope="col">PF</th><th scope="col">P&amp;L after costs</th><th scope="col">Unusable</th></tr></thead>
        <tbody>{([['original', 'Original'], ['profit_trail', 'Profit trail'], ['loss_only', 'Loss limit'], ['loss_and_trail', 'Loss limit + trail']] as const).map(([key, label]) => {
          const result = c.initial_loss_comparison!.arms[key];
          const statuses = c.initial_loss_comparison!.statuses[key] ?? {};
          const unusable = (statuses.missing_quote ?? 0) + (statuses.missing_path ?? 0) + (statuses.invalid_entry ?? 0);
          return <tr key={key}><th scope="row" className="font-normal py-1">{label}</th><td>{researchProfitFactorText(result.profit_factor, c.initial_loss_comparison!.paired_results)}</td><td>{money(result.net_pnl)}</td><td>{unusable}</td></tr>;
        })}</tbody>
      </table>
      <p>{c.initial_loss_comparison.unpaired} of {c.initial_loss_comparison.tracked} plays not yet matched across all four exits. Missing-price plays stay out of this comparison.</p>
      <p>Research only. Your trading exits have not changed.</p>
    </details>}
  </div>;
}

export function ReferenceContractTest({ test: t }: { test: StrategyTickerResearchPair["reference_contract_test"] }) {
  if (!t) return null;
  const firstDate = t.first_test_at ? new Date(`${t.first_test_at.slice(0, 10)}T12:00:00Z`).toLocaleDateString("en-US", {timeZone: "America/New_York", month: "short", day: "numeric", year: "numeric"}) : null;
  return <details className="rounded-lg px-3 py-2" style={{background: "var(--surface-sunken)", color: "var(--ink-muted)"}}>
    <summary className="cursor-pointer"><b style={{color: "var(--ink)"}}>7–21-day option test</b> · {t.option_results} results · PF {researchProfitFactorText(t.control.profit_factor, t.option_results)}</summary>
    <p>{firstDate ? `Started ${firstDate}` : "Starts with the next eligible research play"} · {t.selected} options matched from {t.tracked} plays · {t.result_days} result days</p>
    <p>Uses the paper strategy’s contract-selection rules: nearest expiry, then nearest out-of-the-money strike; $0.80–$10 ask, spread up to 8%. Research uses a $1,000 ceiling, not your account limits.</p>
    <p>{t.minutes}-minute exit · After-cost P&amp;L {money(t.control.net_pnl)} · {t.statuses.missing_quote ?? 0} missing exit prices · {t.statuses.no_contract ?? 0} without a qualifying entry · {t.statuses.invalid_entry ?? 0} invalid or late entries</p>
    <p>Separate from 0–7-day results. These are fresh-quote models, not paper fills or permission to trade.</p>
    {t.profit_protection && <ProfitProtectionComparison comparison={t.profit_protection} reference />}
  </details>;
}
