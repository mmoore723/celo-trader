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
  missing_indicator_state: "Missing matching indicator state", entry_after_session_cutoff: "Entry outside test hours",
};

export function AuthoredExitEvidence({ evidence }: { evidence: StrategyTickerResearchPair["authored_exit_evidence"] }) {
  if (!evidence) return null;
  return <div className="sm:col-span-2 rounded-lg border p-2" style={{ borderColor: "var(--border)" }}>
    <b>Actual exit PF: {researchProfitFactorText(evidence.profit_factor, evidence.option_results)}</b> · {evidence.option_results} results · {evidence.option_result_days} result days
    {evidence.protocol === "ema_structural_2_06r_completed15m_rth_close_corrected_v1" && <p>15-minute exits · Corrected 4:00 PM close</p>}
    <p>{evidence.collecting} open tests · {evidence.pending_quote} awaiting exit price · {evidence.missing_quote + evidence.unmeasurable} missing usable data</p>
    {Object.entries(evidence.reasons).filter(([reason]) => reasons[reason]).map(([reason, count]) => <span key={reason} className="mr-2">{reasons[reason]}: {count}</span>)}
    {evidence.option_results > 0 && <p>Average {money(evidence.average_one_contract_pnl)} · Typical {money(evidence.median_one_contract_pnl)} · After-cost P&amp;L {money(evidence.net_one_contract_pnl)}</p>}
    <ShortTrailComparison comparison={evidence.short_trail_comparison} />
  </div>;
}
