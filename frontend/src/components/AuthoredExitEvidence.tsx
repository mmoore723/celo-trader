import type { StrategyTickerResearchPair } from "../lib/api";
import { researchProfitFactorText } from "../lib/researchPairView.js";
import { ShortTrailComparison } from "./ShortTrailComparison";

const money = (value: number | null) => value == null ? "—" : `$${value.toFixed(2)}`;
const reasons: Record<string, string> = {
  underlying_1_5r_target: "1.5R target reached", underlying_2r_target: "2R target reached",
  underlying_vwap_target: "Entry VWAP target reached",
  underlying_2_06r_target: "2.06R target reached",
  missing_bars: "Missing candles", invalid_bars: "Invalid candles", duplicate_bars: "Repeated candles",
  late_entry_quote: "Late entry price", invalid_entry: "Invalid entry", invalid_levels: "Invalid exit levels",
  missed_session: "Session was not captured",
  missing_exit_state: "Missing matching exit rules",
  or_midpoint_close: "Closed through opening-range middle", eod_1555_cap: "3:55 PM exit",
  premium_target_100_pct: "Option reached +100%",
  prior_high_target: "Earlier high reached", five_minute_close_below_vwap: "5-minute close below VWAP",
  invalid_direction: "Direction does not match the strategy",
  missing_indicator_state: "Missing matching indicator state", entry_after_session_cutoff: "Entry outside test hours",
};

export function AuthoredExitEvidence({ evidence }: { evidence: StrategyTickerResearchPair["authored_exit_evidence"] }) {
  if (!evidence) return null;
  return <div className="sm:col-span-2 rounded-lg border p-2" style={{ borderColor: "var(--border)" }}>
    <b>Actual exit PF: {researchProfitFactorText(evidence.profit_factor, evidence.option_results)}</b> · {evidence.option_results} results · {evidence.option_result_days} result days
    {evidence.partial_exit_comparison && <div>
      <p>One-contract runner above · Two-contract split below</p>
      <p>Split PF: {researchProfitFactorText(evidence.partial_exit_comparison.profit_factor, evidence.partial_exit_comparison.results)} · After-cost P&amp;L {money(evidence.partial_exit_comparison.net_two_contract_pnl)} · {evidence.partial_exit_comparison.partial_sales} partial sales</p>
      <p>Sell one at +30%; exit the other at +100%, the range middle, or 3:55 PM. Sampled quotes can miss brief price touches.</p>
    </div>}
    {evidence.protocol === "ema_structural_2_06r_completed15m_rth_close_corrected_v1" && <p>15-minute exits · Corrected 4:00 PM close</p>}
    {["context_vwap_ker_prior_high_5m_vwap_1555_v1", "context_vwap_displacement_prior_high_5m_vwap_1555_v1"].includes(evidence.protocol) && <p>Earlier high · 5-minute close below VWAP · 3:55 PM cutoff</p>}
    <p>{evidence.collecting} open tests · {evidence.pending_quote} awaiting exit price · {evidence.missing_quote + evidence.unmeasurable} missing usable data</p>
    {Object.entries(evidence.reasons).filter(([reason]) => reasons[reason]).map(([reason, count]) => <span key={reason} className="mr-2">{reasons[reason]}: {count}</span>)}
    {evidence.option_results > 0 && <p>Average {money(evidence.average_one_contract_pnl)} · Typical {money(evidence.median_one_contract_pnl)} · After-cost P&amp;L {money(evidence.net_one_contract_pnl)}</p>}
    <ShortTrailComparison comparison={evidence.short_trail_comparison} />
  </div>;
}
