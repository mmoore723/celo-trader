import { request, type PremiumExitReport } from '../../lib/api';
import { useState } from 'react';
import { useAuth } from '../../contexts/AuthContext';

export function PremiumExitEvidence({ report }: { report?: PremiumExitReport }) {
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const { user }=useAuth();
  if (!report) return null;
  async function approve(rule:string) {
    if (!report || busy || !window.confirm('Apply this approved profit-taking exit to future PAPER entries for this exact pair? Existing positions and live policies stay unchanged.')) return;
    setBusy(true);
    try {
      await request('/api/strategy-health/premium-exits/approve',{method:'POST',body:JSON.stringify({bucket:report.bucket,rule,report_hash:report.fingerprint})});
      setMessage('Saved for new paper entries. Existing positions and live settings unchanged.');
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Approval failed.'); }
    finally { setBusy(false); }
  }
  const money=(n:number|null)=>n == null ? 'Unavailable' : `$${n.toFixed(2)}`;
  return <section className="rounded border p-3 space-y-2" aria-label="Profit-taking exit comparisons">
    <h4 className="font-semibold">Profit-taking exits</h4>
    <p className="text-xs">Hypothetical option bids, not fills. Each exit supplements the original exit. Stops and session liquidation remain active.</p>
    <p className="text-xs">Comparison: {report.baseline_source ?? 'Saved baseline'}.</p>
    {report.candidates.map(c=><details key={c.rule} className="border rounded p-2">
      <summary>{c.label}: {c.selection?.paired_trades ?? 0}/50 initial paired trades; {c.paired_trades}/50 newer holdout trades.</summary>
      <p>Newer holdout: {c.sessions}/20 sessions. {Math.round(c.coverage*100)}% usable coverage. {c.holdout_started_after ? `Trades after ${c.holdout_started_after}.` : 'Starts after the initial evaluation ends.'}</p>
      <p>Baseline net: {money(c.baseline.net_pnl)}. Candidate net: {money(c.candidate.net_pnl)}. Winners turned into losses: {c.baseline_winners_to_losses}.</p>
      <p>Candidate win rate: {c.candidate.win_rate ?? 'Unavailable'}%. Worst loss: {money(c.candidate.worst_loss)}. Drawdown: {money(c.candidate.drawdown)}.</p>
      <p>Paired improvement interval: {c.improvement_interval ? c.improvement_interval.map(money).join(' to ') : 'Not enough sessions'}.</p>
      <p>Confidence: {(c.confidence*100).toFixed(3)}%, adjusted for {c.tested_exits} exit tests in this bucket.</p>
      {c.rule_specification?.arm_dollars_per_contract && <p>Starts watching after ${Number(c.rule_specification.arm_dollars_per_contract).toFixed(6)} profit per contract. A giveback sale must cover the $3.30 modeled costs.</p>}
      {c.research_only && <p>Research only. Cannot be activated.</p>}
      <p>{c.recommendation}. {c.status.replaceAll('_',' ')}.</p>
      {Object.entries(c.exclusions).map(([reason,count])=><p key={reason}>{count} attempts: {reason.replaceAll('_',' ')}</p>)}
      <p>Historical comparison: {c.historical.paired_trades} usable trades. Kept separate from new forward evidence.</p>
      {user?.is_admin && c.promotion_ready && <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={()=>approve(c.rule)}>Approve for new paper entries</button>}
    </details>)}
    {message && <p role="status">{message}</p>}
    {report.execution_validation && <details><summary>Exact deployed-exit comparison for approval</summary><PremiumExitEvidence report={report.execution_validation} /></details>}
    <p className="text-xs">{report.specification}. Updated {report.updated_at}. No exit activated by viewing this page.</p>
  </section>;
}
