import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { request, type StrategyTickerResearchPair } from '../../lib/api';

export function ResearchPairControl({ strategyId, version, ticker, name, trading, pair }: {
  strategyId: string; version: string; ticker: string; name: string; trading: boolean;
  pair: StrategyTickerResearchPair;
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [exit, setExit] = useState('native');
  const [contract, setContract] = useState('native');
  const [comparing, setComparing] = useState(false);
  const selectedExit = pair.exit_comparison.find(item => String(item.minutes) === exit);
  const selectedContract = pair.contract_tests.find(item => item.policy === contract);
  const metrics = (item: { profit_factor: number | 'infinite' | null; net_one_contract_pnl: number; option_results: number }) =>
    `PF ${item.profit_factor ?? 'unavailable'} | $${item.net_one_contract_pnl.toFixed(2)} net | ${item.option_results} priced results`;
  if (!user?.is_admin) return null;
  async function enable() {
    if (busy) return;
    if (comparing || trading) return;
    setBusy(true); setError('');
    try {
      await request('/api/settings/strategies/admin-override', {
        method: 'POST', body: JSON.stringify({ strategy_id: strategyId, strategy_version: version, ticker, enabled: true }),
      });
      setSaved(true); setConfirming(false);
      await Promise.all(['settings', 'strategy-catalog', 'strategy-recommendations', 'strategy-research-matrix',
        'strategy-research-results', 'strategy-research-analytics', 'admin-strategy-controls'].map(key => qc.invalidateQueries({ queryKey: [key] })));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not turn on this pair.');
    } finally { setBusy(false); }
  }
  return <div className="px-3 pb-3 text-xs">
    {saved && <p role="status" style={{ color: 'var(--positive)' }}>Pair permission saved. Account mode and risk limits unchanged. New entries still require valid signals and safety checks.</p>}
    <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => { setSaved(false); setComparing(trading); setConfirming(true); setError(''); }}>{trading ? 'Review tests' : 'Turn on pair'}</button>
    {confirming && createPortal(<dialog open={false} ref={node => { if (node && !node.open) node.showModal(); }}
      onCancel={event => { if (busy) event.preventDefault(); else setConfirming(false); }}
      aria-label={`Test choices for ${ticker} ${name}`} className="card p-5 w-full max-w-2xl max-h-[85vh] overflow-y-auto text-sm"
      style={{ color: 'var(--ink)', background: 'var(--surface)', margin: 'auto' }}>
      <div className="space-y-4">
        <p className="font-semibold text-lg">{ticker} · {name}</p><p className="text-xs">{version}</p>
        <div className="flex gap-2" role="tablist" aria-label="Pair actions"><button type="button" role="tab" aria-selected={!comparing} className={`btn ${!comparing ? 'btn-primary' : 'btn-ghost'}`} disabled={busy} onClick={() => setComparing(false)}>Trading permission</button><button type="button" role="tab" aria-selected={comparing} className={`btn ${comparing ? 'btn-primary' : 'btn-ghost'}`} disabled={busy} onClick={() => setComparing(true)}>Compare research</button></div>
        {comparing ? <>
        <p>Compare recorded tests below. These are hypothetical research results, not broker fills. Highest profit alone does not establish the best choice.</p>
        <label className="block">Exit test
          <select className="input w-full mt-1" value={exit} disabled={busy} onChange={event => setExit(event.target.value)}>
            <option value="native">Current production exit (available to activate)</option>
            {[...pair.exit_comparison].sort((a, b) => b.net_one_contract_pnl - a.net_one_contract_pnl).map(item =>
              <option key={item.minutes} value={String(item.minutes)}>{item.minutes} minutes: {metrics(item)} (research only)</option>)}
          </select>
        </label>
        {selectedExit && <p>{metrics(selectedExit)}. Win rate: {selectedExit.win_rate_pct ?? 'unavailable'}%. Late quotes excluded: {selectedExit.mistimed_quotes_ignored}.</p>}
        <label className="block">Option-selection test
          <select className="input w-full mt-1" value={contract} disabled={busy} onChange={event => setContract(event.target.value)}>
            <option value="native">Current production contract selection (available to activate)</option>
            {[...pair.contract_tests].sort((a, b) => b.net_one_contract_pnl - a.net_one_contract_pnl).map(item =>
              <option key={item.policy} value={item.policy}>{item.label}: {metrics(item)} (research only)</option>)}
          </select>
        </label>
        {selectedContract && <p>{metrics(selectedContract)} across {selectedContract.option_result_days} result days. Profile: {selectedContract.profile_version}. {selectedContract.explanation}</p>}
        <p>Pair quote coverage: {pair.quote_coverage_pct == null ? 'unavailable' : `${pair.quote_coverage_pct}%`}. Comparisons may contain different trades. Selecting two tests is not evidence that their combination was tested.</p>
        <p role="status" style={{ color: 'var(--warning)' }}>Comparison only. These selectors do not configure trading. Research variants require a tested production adapter before they can be activated.</p>
        <button type="button" className="btn btn-primary" onClick={() => { setExit('native'); setContract('native'); setComparing(false); }}>Continue with current production rules</button>
        </> : <>
        <div className="rounded-lg p-3" style={{ background: 'var(--surface-raised)' }}><strong>Current production rules</strong><p className="mt-1">Enables this exact strategy, ticker and version. Keeps its existing exit and contract-selection rules.</p></div>
        <p>Overrides research qualification for this pair. Grants permission in paper and live modes, but does not enable live trading or change account mode. Execution, risk and loss-pause checks still apply.</p>
        {trading && <p role="status">This pair is already enabled. No additional confirmation is needed.</p>}
        </>}
        {error && <p role="alert" style={{ color: 'var(--negative)' }}>{error}</p>}
        <div className="flex gap-2">{!comparing && !trading && <button type="button" className="btn btn-primary" disabled={busy} onClick={enable}>{busy ? 'Saving...' : 'Confirm turn on'}</button>}<button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setConfirming(false)}>Close</button></div>
      </div>
    </dialog>, document.body)}
  </div>;
}
