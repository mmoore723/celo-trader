import { useState } from "react";
import { createPortal } from "react-dom";
import { request, type StrategyTickerRecommendation } from "../../lib/api";
import { strategyName } from "../../lib/strategyIdentity.js";
import { StrategyIdentity } from "./StrategyIdentity";

export type PairDecision = "enable" | "keep_off" | "research_only" | "keep_trading";
const pf = (value: number | "infinite" | null) => value === "infinite" ? "No losses yet" : value == null ? "—" : value.toFixed(2);

type ActivationReview = {
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

export function StrategyRecommendations({ recommendations, onDecision }: {
  recommendations: StrategyTickerRecommendation[];
  onDecision: (item: StrategyTickerRecommendation, decision: PairDecision) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState<StrategyTickerRecommendation | null>(null);
  const [review, setReview] = useState<ActivationReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [choice, setChoice] = useState("");
  const [notes, setNotes] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const reviewPath = (item: StrategyTickerRecommendation) => `/api/settings/strategies/activation/${encodeURIComponent(item.strategy_id)}/${encodeURIComponent(item.ticker)}`;
  async function openReview(item: StrategyTickerRecommendation) {
    setBlocked(item); setReview(null); setReviewError(""); setChoice(""); setNotes(""); setAcknowledged(false); setLoading(true);
    try { setReview(await request<ActivationReview>(`${reviewPath(item)}?version=${encodeURIComponent(item.strategy_version)}`)); }
    catch (err) { setReviewError(err instanceof Error ? err.message : "Could not load evidence. Refresh Settings and try again."); }
    finally { setLoading(false); }
  }
  async function saveApproval() {
    if (!blocked || !review || busy || !acknowledged || !choice) return;
    setBusy(true); setReviewError("");
    try {
      const approval = await request<NonNullable<ActivationReview['approval']>>(reviewPath(blocked), {
        method: 'POST', body: JSON.stringify({version: blocked.strategy_version, token: review.token,
          choice, notes: choice === 'changes' ? notes : '', acknowledged}),
      });
      setReview({...review, approval});
    } catch (err) { setReviewError(err instanceof Error ? err.message : "Approval was not saved."); }
    finally { setBusy(false); }
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
            : `First 14 PF ${pf(item.evidence.training.profit_factor)} · Latest 6 PF ${pf(item.evidence.validation.profit_factor)}`}</p>
          <p className="text-xs mt-1" style={{color: "var(--ink-muted)"}}>Research results, not broker fills.</p>
          {item.blocker && !review && <p className="text-xs mt-2" style={{color: "var(--warning)"}}>{item.blocker}</p>}
          <div className="flex flex-wrap gap-2 mt-3">
            {review ? <><button disabled={busy} className="btn btn-primary" onClick={() => decide(item, "research_only")}>Move to research only</button><button disabled={busy} className="btn btn-ghost" onClick={() => decide(item, "keep_trading")}>Keep trading</button></>
              : <><button type="button" disabled={busy || loading} className="btn btn-primary" onClick={() => openReview(item)}>Review activation</button><button disabled={busy} className="btn btn-ghost" onClick={() => decide(item, "keep_off")}>Keep off</button></>}
          </div>
        </article>)}
        <details className="text-xs mt-3" style={{color: "var(--ink-muted)"}}><summary className="cursor-pointer">What triggers this?</summary><p className="mt-2">{review
          ? "The latest 10 non-overlapping completed research tests have PF below 1.0 and a net loss after costs. Moving to research only stops new entries for this pair, not other tickers or existing-position exits."
          : "20 non-overlapping completed tests: first 14 and latest 6 each need PF 1.5+, the typical result must be positive, and no single winner may supply over 35% of gains. No minimum day count. Every research signal is still collected. These checks do not guarantee future profit."}</p></details>
      </section>;
    })}
    {blocked && createPortal(<dialog ref={node => { if (node && !node.open) node.showModal(); }}
      onCancel={event => { if (busy || loading) event.preventDefault(); else setBlocked(null); }} aria-labelledby="strategy-unavailable-title"
      className="card p-5 w-full max-w-2xl max-h-[85vh] overflow-y-auto text-sm"
      style={{ margin: "auto", color: "var(--ink)", background: "var(--surface)" }}>
      <h3 id="strategy-unavailable-title" className="font-semibold text-lg">Review activation</h3>
      <p className="mt-2">{blocked.ticker} · {strategyName(blocked.display_name)} · {blocked.strategy_version}</p>
      {loading && <p role="status" className="mt-3">Loading saved evidence...</p>}
      {reviewError && <p role="alert" className="mt-3" style={{color: 'var(--negative)'}}>{reviewError}</p>}
      {error && <p role="alert" className="mt-3" style={{color: 'var(--negative)'}}>{error}</p>}
      {review && <div className="space-y-4 mt-4">
        <p role="status">{review.can_enable ? 'Execution checks allow activation. Review the evidence before confirming.' : review.blocker}</p>
        <section><h4 className="font-semibold">Evidence, not broker fills</h4>
          <p>{review.evidence.independent_trades} non-overlapping tests; {review.evidence.overlapping_trades} overlapping results excluded from qualification.</p>
          <p className="text-xs">{review.evidence.first_test_at ?? 'Unknown start'} to {review.evidence.last_test_at ?? 'Unknown end'}</p>
          <table className="w-full mt-2 text-xs"><thead><tr><th className="text-left">Sample</th><th>Tests</th><th>PF</th><th>Net / 1 contract</th><th>Win rate</th></tr></thead>
            <tbody>{(['training', 'validation'] as const).map(key => <tr key={key}><td>{key === 'training' ? 'First 14' : 'Latest 6'}</td>{['option_results', 'profit_factor', 'net_one_contract_pnl', 'win_rate_pct'].map(field => <td className="text-center" key={field}>{review.evidence[key][field] ?? 'Unavailable'}</td>)}</tr>)}</tbody></table>
          <p className="text-xs mt-2">Net figures use the research model's recorded costs. They are not guaranteed fills or live validation.</p>
          <details className="mt-2"><summary>Coverage and missing data</summary><dl>{Object.entries(review.coverage).map(([key,value]) => <div key={key} className="mt-1"><dt>{key.replaceAll('_',' ')}</dt><dd>{value == null ? 'Not recorded in this snapshot' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></details>
        </section>
        <section><h4 className="font-semibold">Existing rules</h4><p>{review.rules.entry ?? 'A verified plain-English entry definition is not available here. Implementation review must resolve it, not guess.'}</p><p className="mt-2">{review.rules.exit ?? 'Exit definition requires implementation review.'}</p>
          <details className="mt-2"><summary>Exact recorded parameters</summary><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(review.rules.parameters, null, 2)}</pre><p className="break-all text-xs">Source: {review.rules.source_sha256 ?? 'Not pinned here'}</p></details>
          <details className="mt-2"><summary>Current research contract profile</summary><pre className="whitespace-pre-wrap text-xs">{review.rules.current_research_contract_profile ? JSON.stringify(review.rules.current_research_contract_profile, null, 2) : 'Profile not verified in this snapshot. Implementation review must verify contract parity.'}</pre></details>
          <p className="mt-2">{review.sizing} Account default: {review.rules.account_risk_fraction == null ? 'automatic sizing' : `${(review.rules.account_risk_fraction * 100).toFixed(1)}%`}. Existing strategy overrides still apply.</p>
        </section>
        <section><h4 className="font-semibold">Readiness</h4><p>{review.test_requirement}</p><p>{review.tests}</p></section>
        {review.execution_review_errors.length > 0 && <p role="status">Execution review blocked: {review.execution_review_errors.join(', ')}. Existing review records do not match current code; approval cannot bypass this.</p>}
        {review.previous_approvals.length > 0 && <details><summary>Previous approvals (evidence or rules have changed)</summary>{review.previous_approvals.map(a=><p key={a.token}>{a.status.replaceAll('_',' ')}: {a.created_at}. New review required for this snapshot.</p>)}</details>}
        {review.approval ? <p role="status" className="rounded border p-3">{review.approval.status === 'changes_requested' ? 'Changes saved for review.' : 'Implementation and testing approved.'} Saved {review.approval.created_at}. {review.can_enable ? 'Activation is a separate confirmation below.' : 'Backend implementation and execution validation are still pending. This does not start an automatic coding worker.'}</p> : <section className="space-y-3">
          <label className="block">Which rules should be implemented?<select className="input w-full mt-1" value={choice} onChange={e=>setChoice(e.target.value)} disabled={busy}><option value="">Choose</option><option value="exact">Keep the exact existing research rules</option><option value="changes">I need changes or clarification</option></select></label>
          {choice === 'changes' && <label className="block">What needs to change?<textarea className="input w-full" maxLength={4000} value={notes} onChange={e=>setNotes(e.target.value)} disabled={busy}/></label>}
          <label className="flex gap-2"><input type="checkbox" checked={acknowledged} onChange={e=>setAcknowledged(e.target.checked)} disabled={busy}/>I reviewed the hypothetical evidence. Approve implementation and testing only, not trading or risk changes.</label>
          <button type="button" className="btn btn-primary" disabled={busy || !choice || !acknowledged || (choice === 'changes' && !notes.trim())} onClick={saveApproval}>{busy ? 'Saving...' : 'Save implementation approval'}</button>
        </section>}
        {review.can_enable && review.approval?.status === 'implementation_approved' && <button type="button" className="btn btn-primary" disabled={busy} onClick={async()=>{await decide({...blocked, can_enable:true}, 'enable');}}>Turn on · {review.account_mode}</button>}
        <p className="text-xs">Reviewing or saving approval does not enable trading. Existing positions, risk limits and live-trading status stay unchanged.</p>
      </div>}
      <button type="button" className="btn btn-ghost mt-4" disabled={busy || loading} onClick={() => setBlocked(null)}>Close</button>
    </dialog>, document.body)}
  </>;
}
