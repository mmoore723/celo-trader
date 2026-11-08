import { useQuery } from '@tanstack/react-query';
import { api, request } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

type Bucket = { strategy: string; ticker: string; version: string; registrations: number; contracts: number; pending: number; late: number; last_collection: string | null; max_gap_seconds: number; gaps_over_10: number; errors: string[]; missing_inputs: string[] };
type Health = { status: string; heartbeat_at?: string; worker_stale: boolean; error?: string; buckets: Bucket[]; discovery?: { blocked?: Record<string, number> } };

export function FastCaptureStatus() {
  const { user } = useAuth();
  const settings = useQuery({ queryKey: ['fast-capture-scope', user?.user_id], queryFn: () => api.settings.get(), staleTime: 15_000, refetchInterval: 30_000, enabled: !!user });
  const scope = `${user?.user_id}:${settings.data?.active_broker_account_id}:${settings.data?.paper_trading}`;
  const query = useQuery({ queryKey: ['fast-capture', scope], queryFn: () => request<Health>('/api/session-capture/fast'), enabled: !!settings.data, staleTime: 15_000, refetchInterval: 30_000 });
  const data = query.data;
  return <aside className="card p-3 text-sm space-y-2" aria-label="Research quote capture">
    <h2 className="font-semibold">Research quote capture</h2>
    {query.error || settings.error ? <p role="alert">Capture status unavailable.</p> : !data ? <p>Loading saved capture status...</p> : <>
      <p>{data.worker_stale ? 'Worker not verified' : data.status.replaceAll('_', ' ')}. Last report: {data.heartbeat_at ? new Date(data.heartbeat_at).toLocaleString() : 'Not received'}.</p>
      <p className="text-xs">Collecting quotes only. This does not start an exit experiment or change trading. Contracts rotate in batches; a five-second request interval is not a five-second guarantee for every contract.</p>
      {data.error && <p role="alert">{data.error}</p>}
      {!!Object.keys(data.discovery?.blocked ?? {}).length && <p role="alert">Registration problems: {Object.entries(data.discovery?.blocked ?? {}).map(([reason, count]) => `${reason.replaceAll('_', ' ')} (${count})`).join('; ')}</p>}
      <details><summary>{data.buckets.length} strategy/ticker/version groups with active capture registrations</summary>
        {!data.buckets.length && <p className="text-xs">No contracts currently registered through a future capture deadline. This does not mean the collector has captured a full session.</p>}
        {data.buckets.map(b => <div className="border-t py-2 text-xs" key={`${b.strategy}:${b.ticker}:${b.version}`}>
          <p className="font-medium">{b.ticker} / {b.strategy} / {b.version || 'Version missing'}</p>
          <p>{b.registrations} registrations, {b.contracts} contracts. Never received: {b.pending}. Last receipt older than 10 seconds: {b.late} (includes time outside market hours).</p>
          <p>Last receipt: {b.last_collection ? new Date(b.last_collection).toLocaleString() : 'None'}. Longest wall-clock gap: {b.max_gap_seconds.toFixed(1)}s. Gaps over 10s: {b.gaps_over_10}. Gaps can include overnight periods.</p>
          {[...b.errors, ...b.missing_inputs].length > 0 && <p>{[...b.errors, ...b.missing_inputs].map(s => s.replaceAll('_', ' ')).join('; ')}</p>}
        </div>)}
      </details>
    </>}
  </aside>;
}
