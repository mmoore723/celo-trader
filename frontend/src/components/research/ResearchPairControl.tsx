import { useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { request, type StrategyTickerResearchPair } from '../../lib/api';
import { PremiumExitEvidence } from './PremiumExitEvidence';

export function ResearchPairControl({ strategyId, version, ticker, name, trading, pair, initiallyOpen = false, onClose, evidence, blockedReason }: {
  strategyId: string; version: string; ticker: string; name: string; trading: boolean;
  pair: StrategyTickerResearchPair;
  initiallyOpen?: boolean; onClose?: () => void; evidence?: ReactNode; blockedReason?: string | null;
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(initiallyOpen);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [exit, setExit] = useState('native');
  const [contract, setContract] = useState('native');
  const [acknowledged, setAcknowledged] = useState(false);
  const connection = useQuery({
    queryKey: ['activation-capability', strategyId, version, ticker],
    queryFn: () => request<{ready: boolean; reason: string | null; configurable_tests: boolean; baseline_exit: string | null; explanation: string}>(
      `/api/settings/strategies/activation-capability?${new URLSearchParams({strategy_id: strategyId, strategy_version: version, ticker})}`),
    enabled: confirming && !!user?.is_admin, staleTime: 0, retry: false,
  });
  const connectionReady = connection.data?.ready === true && !connection.isFetching && !connection.isError;
  const selectedExit = pair.exit_comparison.find(item => String(item.minutes) === exit);
  const selectedContract = pair.contract_tests.find(item => item.policy === contract);
  const metrics = (item: { profit_factor: number | 'infinite' | null; net_one_contract_pnl: number; option_results: number }) =>
    `PF ${item.profit_factor ?? 'unavailable'} | $${item.net_one_contract_pnl.toFixed(2)} net | ${item.option_results} priced results`;
  if (!user?.is_admin) return null;
  function close() { setConfirming(false); onClose?.(); }
  async function enable() {
    if (busy) return;
    if (!acknowledged) return;
    if (blockedReason || !connectionReady) return;
    setBusy(true); setError('');
    try {
      await request('/api/settings/strategies/admin-override', {
        method: 'POST', body: JSON.stringify({ strategy_id: strategyId, strategy_version: version, ticker, enabled: true,
          exit_minutes: exit === 'native' ? null : Number(exit),
          contract_policy: contract === 'native' ? null : contract }),
      });
      setSaved(true); close();
      await Promise.all(['settings', 'strategy-catalog', 'strategy-recommendations', 'strategy-research-matrix',
        'strategy-research-results', 'strategy-research-analytics', 'admin-strategy-controls'].map(key => qc.invalidateQueries({ queryKey: [key] })));
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Could not save this pair.';
      try { setError(JSON.parse(message.slice(message.indexOf('{'))).detail || message); }
      catch { setError(message); }
    } finally { setBusy(false); }
  }
  return <div className="px-3 pb-3 text-xs">
    {saved && <p role="status" style={{ color: 'var(--positive)' }}>Pair and selected settings saved for new entries. Existing positions and risk limits unchanged.</p>}
    {!initiallyOpen && <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => { setSaved(false); setConfirming(true); setAcknowledged(false); setError(''); }}>{trading ? 'Change pair settings' : 'Turn on pair'}</button>}
    {confirming && createPortal(<dialog ref={node => { if (node && !node.open) node.showModal(); }}
      onCancel={event => { if (busy) event.preventDefault(); else close(); }}
      aria-label={`Settings for ${ticker} ${name}`} className="card p-5 w-full max-w-2xl max-h-[85vh] overflow-y-auto text-sm"
      style={{ color: 'var(--ink)', background: 'var(--surface)', margin: 'auto' }}>
      <div className="space-y-4">
        <p className="font-semibold text-lg">{ticker} · {name}</p><p className="text-xs">{version}</p>
        <p className="text-xs">One shared strategy, with approved settings for {ticker}.</p>
        {connection.isFetching && <p role="status">Checking the execution connection...</p>}
        {connection.isError && <p role="alert">Could not verify the connection. Close and reopen to retry. Nothing has been enabled.</p>}
        {connection.data && <p role="status">{connection.data.ready ? connection.data.explanation : connection.data.reason}</p>}
        {evidence}
        <PremiumExitEvidence report={pair.premium_exit_research} />
        <label className="block">Exit setting
          <select className="input w-full mt-1" value={exit} disabled={busy || !connectionReady || !connection.data?.configurable_tests} onChange={event => { setExit(event.target.value); setAcknowledged(false); }}>
            <option value="native">Original strategy exit</option>
            {[...pair.exit_comparison].filter(item => [30,60,90,120].includes(item.minutes)).sort((a,b)=>a.minutes-b.minutes).map(item =>
              <option key={item.minutes} value={String(item.minutes)}>{item.minutes} minutes: {metrics(item)}</option>)}
          </select>
        </label>
        {selectedExit && <p className="text-xs">{metrics(selectedExit)}. Win rate: {selectedExit.win_rate_pct ?? 'unavailable'}%. Late quotes excluded: {selectedExit.mistimed_quotes_ignored}.</p>}
        <label className="block">Contract setting
          <select className="input w-full mt-1" value={contract} disabled={busy || !connectionReady || !connection.data?.configurable_tests} onChange={event => { setContract(event.target.value); setAcknowledged(false); }}>
            <option value="native">Original contract selection</option>
            {pair.contract_tests.map(item => <option key={item.policy} value={item.policy}>{item.label}: {metrics(item)}</option>)}
          </select>
        </label>
        {selectedContract && <p className="text-xs">{metrics(selectedContract)} across {selectedContract.option_result_days} result days. {selectedContract.explanation}</p>}
        <div className="rounded border p-3"><strong>Will apply to new entries</strong><p>Exit: {exit === 'native' ? (connection.data?.baseline_exit || 'original strategy rules') : `${exit} minutes after fill, replacing the strategy exit`}. Contract: {selectedContract?.label ?? 'original selection'}.</p><p>Mandatory safety exits and session liquidation stay active. Existing positions keep their entry-time rules.</p></div>
        <p className="text-xs">Hypothetical research, not broker fills. Selecting two tests is not evidence that their combination was tested.</p>
        <label className="flex gap-2"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={event=>setAcknowledged(event.target.checked)}/>Use these settings for this pair. Apply the same configuration to paper and live, but do not enable live trading or change risk limits.</label>
        {error && <p role="alert" style={{ color: 'var(--negative)' }}>{error}</p>}
        {blockedReason && <p role="status" style={{ color: 'var(--warning)' }}>{blockedReason}</p>}
        <div className="flex gap-2"><button type="button" className="btn btn-primary" disabled={busy || !acknowledged || !!blockedReason || !connectionReady} onClick={enable}>{busy ? 'Saving...' : trading ? 'Confirm settings' : 'Confirm turn on'}</button><button type="button" className="btn btn-ghost" disabled={busy} onClick={close}>Close</button></div>
      </div>
    </dialog>, document.body)}
  </div>;
}
