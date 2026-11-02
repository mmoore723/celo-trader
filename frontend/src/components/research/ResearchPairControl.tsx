import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { request } from '../../lib/api';

export function ResearchPairControl({ strategyId, version, ticker, name, trading }: {
  strategyId: string; version: string; ticker: string; name: string; trading: boolean;
}) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  if (!user?.is_admin) return null;
  async function enable() {
    if (busy) return;
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
    {saved ? <p role="status" style={{ color: 'var(--positive)' }}>Pair permission saved. Account mode and risk limits unchanged. New entries still require valid signals and safety checks.</p>
      : trading ? <span className="badge badge-green">Trading on</span>
      : !confirming ? <button type="button" className="btn btn-primary btn-sm" onClick={() => { setConfirming(true); setError(''); }}>Turn on pair</button>
      : <div className="rounded-lg border p-3 space-y-2" style={{ borderColor: 'var(--border)' }}>
        <p className="font-semibold">Turn on {ticker} / {name} / {version}?</p>
        <p>Overrides research qualification for this pair. Grants permission in paper and live modes, but does not enable live trading or change account mode. Execution, risk and loss-pause checks still apply.</p>
        <div className="flex gap-2"><button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={enable}>{busy ? 'Saving...' : 'Confirm turn on'}</button><button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button></div>
      </div>}
    {error && <p role="alert" className="mt-2" style={{ color: 'var(--negative)' }}>{error}</p>}
  </div>;
}
