import { useState } from "react";
import { createPortal } from "react-dom";
import { request, type PremiumExitReport, type StrategyTickerRecommendation, type StrategyTickerResearchPair } from "../../lib/api";
import { PremiumExitEvidence } from '../research/PremiumExitEvidence';
import { strategyName } from "../../lib/strategyIdentity.js";
import { StrategyIdentity } from "./StrategyIdentity";
import { ResearchPairControl } from "../research/ResearchPairControl";
import { evidencePeriod } from "../../lib/evidencePeriod";
import { ruleLabel, ruleValue } from "../../lib/researchRuleText";

export type PairDecision = "enable" | "keep_off" | "research_only" | "keep_trading";
const pf = (value: number | "infinite" | null) => value === "infinite" ? "No losses yet" : value == null ? "—" : value.toFixed(2);

type ActivationReview = {
  research_pair: StrategyTickerResearchPair;
  token: string; can_enable: boolean; blocker: string | null; account_mode: string;
  rules: {entry: string | null; exit: string | null; parameters: Record<string, unknown>; source_sha256: string | null;
    current_research_contract_profile?: Record<string, unknown> | null; account_risk_fraction: number | null};
  evidence: {training: Record<string, number | string | null>; validation: Record<string, number | string | null>;
    independent_trades: number; overlapping_trades: number; first_test_at: string | null; last_test_at: string | null};
  coverage: Record<string, unknown>; sizing: string; tests: string; test_requirement: string;
  approval: {status: string; created_at: string} | null;
  previous_approvals: {status: string; created_at: string; token: string}[];
  execution_review_errors: string[];
};

export function StrategyRecommendations({ recommendations, onDecision, premiumReviews = [] }: {
  premiumReviews?: PremiumExitReport[];
  recommendations: StrategyTickerRecommendation[];
  onDecision: (item: StrategyTickerRecommendation, decision: PairDecision) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [premiumBucket,setPremiumBucket]=useState('');
  const premiumReport=premiumReviews.find(r=>r.bucket===premiumBucket) ?? premiumReviews[0];
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState<StrategyTickerRecommendation | null>(null);
  const [review, setReview] = useState<ActivationReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const reviewPath = (item: StrategyTickerRecommendation) => `/api/settings/strategies/activation/${encodeURIComponent(item.strategy_id)}/${encodeURIComponent(item.ticker)}`;
  async function openReview(item: StrategyTickerRecommendation) {
    setBlocked(item); setReview(null); setReviewError(""); setLoading(true);
    try { setReview(await request<ActivationReview>(`${reviewPath(item)}?version=${encodeURIComponent(item.strategy_version)}`)); }
    catch (err) { setReviewError(err instanceof Error ? err.message : "Could not load evidence. Refresh Settings and try again."); }
    finally { setLoading(false); }
  }
  async function decide(item: StrategyTickerRecommendation, action: PairDecision) {
    if (busy) return;
    if (action === "enable" && !item.can_enable) { await openReview(item); return; }
    if (action === "enable" && !window.confirm(`Allow ${strategyName(item.display_name)} to place ${item.account_mode} orders on ${item.ticker}?`)) return;
    setBusy(true); setError("");
    try { await onDecision(item, action); setBlocked(null); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not save your choice. Try again."); }
    finally { setBusy(false); }
  }
  return <>
    <section className="card p-4" aria-label="Profit-taking Auto Review">
      <h3 className="text-sm font-semibold">Profit-taking exit review</h3>
      <p className="text-xs">Each exit is checked separately against the recorded deployed exit. Insufficient evidence prevents approval.</p>
      {premiumReport ? <>
        <label className="text-sm">Strategy and ticker <select className="input my-2" value={premiumReport.bucket} onChange={e=>setPremiumBucket(e.target.value)}>
          {premiumReviews.map(r=><option key={r.bucket} value={r.bucket}>{strategyName(r.strategy_id)} · {r.ticker} · {r.strategy_version}</option>)}
        </select></label>
        <PremiumExitEvidence report={premiumReport} />
      </> : <p className="text-xs">The background worker has not published an exit review for this account yet.</p>}
    </section>
    {error && <p role="alert" className="text-sm" style={{color: "var(--negative)"}}>{error}</p>}
    {(["new_match", "review_active"] as const).map(kind => {
      const rows = recommendations.filter(item => item.kind === kind);
      const review = kind === "review_active";
      return <section key={kind} className="card p-4">
        <h3 className="text-sm font-semibold">{review ? "Review active strategies" : "New strategy matches"}</h3>
        <p className="text-xs mt-1 mb-3" style={{color: "var(--ink-muted)"}}>{review
          ? "Review weaker research results here. Actual closed-trade PF below 1 automatically stops new entries for that account and pair. Open positions keep their exits."
          : "Pairs appear here after passing the test checks. You decide whether to allow trading."}</p>
        {!rows.length && <p className="text-xs" style={{color: "var(--ink-muted)"}}>{review ? "No active pairs meet the review trigger." : "No new pairs have passed all checks yet."}</p>}
        {rows.map(item => <article key={`${item.strategy_id}:${item.ticker}`} className="rounded-lg border p-3 mt-2" style={{borderColor: "var(--border)"}}>
          <strong className="text-sm">{strategyName(item.display_name)}</strong>
          <StrategyIdentity id={item.strategy_id} version={item.strategy_version} tickers={[item.ticker]} label={review ? "Review ticker" : "Suggested ticker"} />
          <p className="text-xs mt-1" style={{color: review ? "var(--negative)" : "var(--positive)"}}>{review
            ? `Latest ${item.completed_trades} non-overlapping tests: PF ${pf(item.profit_factor)} · $${item.net_pnl.toFixed(2)} after costs`
            : `${evidencePeriod(item.evidence.training)}: PF ${pf(item.evidence.training.profit_factor)} · ${evidencePeriod(item.evidence.validation)}: PF ${pf(item.evidence.validation.profit_factor)}`}</p>
          <p className="text-xs mt-1" style={{color: "var(--ink-muted)"}}>Research results, not broker fills.</p>
          {item.blocker && !review && <p className="text-xs mt-2" style={{color: "var(--warning)"}}>{item.blocker}</p>}
          <div className="flex flex-wrap gap-2 mt-3">
            {review ? <><button disabled={busy} className="btn btn-primary" onClick={() => decide(item, "research_only")}>Move to research only</button><button disabled={busy} className="btn btn-ghost" onClick={() => decide(item, "keep_trading")}>Keep trading</button></>
              : <><button type="button" disabled={busy || loading} className="btn btn-primary" onClick={() => openReview(item)}>Review activation</button><button disabled={busy} className="btn btn-ghost" onClick={() => decide(item, "keep_off")}>Keep off</button></>}
          </div>
        </article>)}
        <details className="text-xs mt-3" style={{color: "var(--ink-muted)"}}><summary className="cursor-pointer">What triggers this?</summary><p className="mt-2">{review
          ? "The latest 10 non-overlapping completed research tests have PF below 1.0 and a net loss after costs. Moving to research only stops new entries for this pair, not other tickers or existing-position exits."
          : "20 non-overlapping completed tests: split chronologically into groups of 14 and 6; both date ranges need PF 1.5+, the typical result must be positive, and no single winner may supply over 35% of gains. No minimum day count. Every research signal is still collected. These checks do not guarantee future profit."}</p></details>
      </section>;
    })}
    {blocked && !review && createPortal(<dialog ref={node => { if (node && !node.open) node.showModal(); }}
      onCancel={() => setBlocked(null)} className="card p-5" style={{margin:"auto"}} aria-label="Loading activation">
      <p>{loading ? 'Loading saved evidence...' : reviewError}</p>
      {!loading && <button className="btn btn-ghost" onClick={()=>openReview(blocked)}>Retry</button>}
      <button className="btn btn-ghost" onClick={()=>setBlocked(null)}>Close</button>
    </dialog>, document.body)}
    {blocked && review && <ResearchPairControl key={review.token} strategyId={blocked.strategy_id}
      ticker={blocked.ticker} version={blocked.strategy_version} name={strategyName(blocked.display_name)}
      trading={false} pair={review.research_pair} initiallyOpen onClose={()=>setBlocked(null)}
      blockedReason={!review.can_enable ? review.blocker || 'This strategy has no verified order route yet. It cannot be enabled.' : null}
      evidence={<div className="space-y-3">
        <section><h4 className="font-semibold">Research checks passed</h4>
          <p>{review.evidence.independent_trades} non-overlapping tests. Research results, not broker fills.</p>
          <table className="w-full text-xs mt-2"><thead><tr><th className="text-left">Test dates (Eastern)</th><th>Tests</th><th>PF</th><th>Net / contract</th><th>Win rate</th></tr></thead>
            <tbody>{(['training','validation'] as const).map(key=><tr key={key}><td>{evidencePeriod(review.evidence[key])}</td>
              {['option_results','profit_factor','net_one_contract_pnl','win_rate_pct'].map(field=><td className="text-center" key={field}>{review.evidence[key][field] ?? 'Unavailable'}</td>)}</tr>)}</tbody>
          </table>
        </section>
        <details><summary>Exact recorded parameters</summary>
          <p>{review.rules.entry ?? 'Entry rules stay unchanged.'}</p><p>{review.rules.exit ?? 'Original strategy exit stays unchanged unless you choose a timed exit below.'}</p>
          <dl>{Object.entries(review.rules.parameters).map(([key,value])=><div key={key}><dt className="font-medium">{ruleLabel(key)}</dt><dd>{ruleValue(key,value)}</dd></div>)}</dl>
        </details>
        <details><summary>Current research contract profile</summary>
          {review.rules.current_research_contract_profile ? <dl>{Object.entries(review.rules.current_research_contract_profile).map(([key,value])=><div key={key}><dt className="font-medium">{ruleLabel(key)}</dt><dd>{ruleValue(key,value)}</dd></div>)}</dl> : <p>No verified contract profile is recorded for this version.</p>}
        </details>
        <section><h4 className="font-semibold">Readiness</h4><p>{review.can_enable ? 'Ready to enable with the settings you choose below. Existing risk limits still apply.' : 'Not ready to trade. The execution route must be verified before this pair can be enabled.'}</p></section>
      </div>}/>}
  </>;
}
