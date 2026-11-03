import type { PairRecommendationEvidence } from "../../lib/api";
import { profitFactorText } from "../../lib/researchPairView.js";
import { evidencePeriod } from "../../lib/evidencePeriod";

export function QualificationEvidence({ evidence }: { evidence?: PairRecommendationEvidence }) {
  if (!evidence) return <p className="text-xs mt-2">Qualification data unavailable. No approval implied.</p>;
  return <div className="text-xs mt-2 space-y-1">
    <p><b>{evidence.independent_trades} independent tests</b>{evidence.remaining_trades > 0
      ? ` · ${evidence.remaining_trades} more needed`
      : " · Required test count met"}</p>
    <p style={{ color: "var(--ink-muted)" }}>Overlapping tests do not count toward qualification.</p>
    <p>{evidencePeriod(evidence.training)}: PF <b>{profitFactorText(evidence.training.profit_factor)}</b></p>
    <p>{evidencePeriod(evidence.validation)}: PF <b>{profitFactorText(evidence.validation.profit_factor)}</b></p>
    <p style={{ color: "var(--ink-muted)" }}>Uses the latest 20 independent tests, not the all-results PF above.</p>
    {evidence.qualified
      ? <p style={{ color: "var(--positive)" }}>Research checks passed. Trading approval is separate in Settings.</p>
      : <div style={{ color: "var(--warning)" }}><b>Still needed:</b><ul className="list-disc pl-4">{(evidence.reasons.length ? evidence.reasons : ["Qualification checks are incomplete."]).map(reason => <li key={reason}>{reason}</li>)}</ul></div>}
  </div>;
}
