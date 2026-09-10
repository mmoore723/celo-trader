import type { StrategyTickerResearchPair } from "../lib/api";
import { researchProfitFactorText } from "../lib/researchPairView.js";

const money = (n: number | null) => n == null ? "—" : `$${n.toFixed(2)}`;
export function ProfitProtectionComparison({ comparison: c }: { comparison: StrategyTickerResearchPair["profit_protection_comparison"] }) {
  if (!c) return null;
  return <div className="rounded-lg px-3 py-2" style={{ background: "var(--surface-sunken)", color: "var(--ink-muted)" }}>
    <b style={{ color: "var(--ink)" }}>Profit protection test</b> · {c.paired_results} matched plays · {c.paired_days} days
    {c.paired_results > 0 ? <p>30-minute exit PF {researchProfitFactorText(c.control.profit_factor, c.paired_results)} → Option trail PF {researchProfitFactorText(c.trail.profit_factor, c.paired_results)} · Average change {money(c.average_improvement)} per contract</p>
      : <p>No matched results yet. Testing whether an option-price trail keeps more profit.</p>}
    <details className="mt-1"><summary className="cursor-pointer">Test rules and missing data</summary>
      <p>Same play, option, and entry ask. Both exit by 30 minutes. Research only; trading rules stay unchanged.</p>
      <p>The trail starts after the option gains its modeled costs plus 3 entry spreads. It follows 2 spreads behind the best observed bid and never moves backward.</p>
      <p>{c.unpaired} of {c.tracked} plays not yet comparable · {c.statuses.missing_path ?? 0} incomplete price paths · {c.statuses.missing_quote ?? 0} missing exit prices</p>
      {c.paired_results > 0 && <p>After-cost P&amp;L: 30-minute {money(c.control.net_pnl)} · Trail {money(c.trail.net_pnl)} · Typical change {money(c.median_improvement)}</p>}
      <p>Sampled quotes can miss brief moves. These are modeled research results, not broker fills or permission to trade.</p>
    </details>
  </div>;
}
