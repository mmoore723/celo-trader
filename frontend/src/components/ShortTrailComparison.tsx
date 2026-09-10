import type { StrategyTickerResearchPair } from "../lib/api";
import { researchProfitFactorText } from "../lib/researchPairView.js";

type Evidence = NonNullable<StrategyTickerResearchPair["authored_exit_evidence"]>;
const money = (n: number | null) => n == null ? "—" : `$${n.toFixed(2)}`;

export function ShortTrailComparison({ comparison: c }: { comparison: Evidence["short_trail_comparison"] }) {
  if (!c) return null;
  return <div className="mt-2 border-t pt-2" style={{ borderColor: "var(--border)" }}>
    <b>Short trail test</b> · {c.paired_results} matched plays · {c.paired_days} days
    <p>Testing a stop that follows the stock’s lowest price. Research only.</p>
    {c.paired_results > 0 ? <>
      <p>Original PF {researchProfitFactorText(c.original.profit_factor, c.paired_results)} → Corrected PF {researchProfitFactorText(c.corrected.profit_factor, c.paired_results)}</p>
      <p>Average change {money(c.average_improvement)} · Typical change {money(c.median_improvement)} per contract, after costs</p>
      <details><summary>Same-play comparison</summary>
        <p>Original P&amp;L {money(c.original.net_pnl)} · Corrected {money(c.corrected.net_pnl)}</p>
        <p>Largest drop: original {money(c.original.maximum_drawdown)} · corrected {money(c.corrected.maximum_drawdown)}</p>
      </details>
    </> : <p>No matched results yet. Both exits need a usable option price.</p>}
    <p>{c.unpaired} of {c.tracked} tests not yet comparable. No trading rules changed.</p>
  </div>;
}
