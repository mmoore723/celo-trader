import type { StrategyTickerResearchPair } from "../lib/api";
import { researchProfitFactorText } from "../lib/researchPairView.js";

const money = (value: number | null) => value == null ? "—" : `$${value.toFixed(2)}`;
const reasons: Record<string, string> = {
  missing_bars: "Missing candles", invalid_bars: "Invalid candles", duplicate_bars: "Repeated candles",
  late_entry_quote: "Late entry price", invalid_entry: "Invalid entry", invalid_levels: "Invalid exit levels",
  missed_session: "Session was not captured",
};

export function AuthoredExitEvidence({ evidence }: { evidence: StrategyTickerResearchPair["authored_exit_evidence"] }) {
  if (!evidence) return null;
  return <div className="sm:col-span-2 rounded-lg border p-2" style={{ borderColor: "var(--border)" }}>
    <b>Actual exit PF: {researchProfitFactorText(evidence.profit_factor, evidence.option_results)}</b> · {evidence.option_results} results · {evidence.option_result_days} result days
    <p>{evidence.collecting} open tests · {evidence.pending_quote} awaiting exit price · {evidence.missing_quote + evidence.unmeasurable} missing usable data</p>
    {Object.entries(evidence.reasons).filter(([reason]) => reasons[reason]).map(([reason, count]) => <span key={reason} className="mr-2">{reasons[reason]}: {count}</span>)}
    {evidence.option_results > 0 && <p>Average {money(evidence.average_one_contract_pnl)} · Typical {money(evidence.median_one_contract_pnl)} · After-cost P&amp;L {money(evidence.net_one_contract_pnl)}</p>}
  </div>;
}
