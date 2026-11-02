import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { api, request } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

type Metrics = { net: number | null; win_rate: number | null; profit_factor: number | null; worst_loss: number | null; drawdown: number | null };
type Candidate = { id: string; version: string; name: string; baseline_metrics?: Metrics; metrics?: Metrics; improvement?: number | null; interval?: [number, number] | null; winners_to_losses?: number | null; pairs?: number; sessions?: number; coverage?: number | null; status?: string };
type Bucket = { id: string; name: string; strategy: string; ticker: string; version: string; revision: string; mode: string; status: string; recommendation: string; result_kind: string; baseline: string; candidates: Candidate[]; pairs: number; sessions: number; required_pairs: number | null; required_sessions: number | null; coverage: number | null; last_collection: string | null; updated_at: string; missing: string[]; paper_policy: string | null; live_policy: string | null; policy_match: string };
type Detail = { rules: unknown; candidates: unknown[]; history: unknown[]; exclusions: unknown[]; evidence: unknown[]; chart: { candidate_id: string; pair_id: string; time: string; baseline: number; candidate: number }[] };
const number = (value: number | null | undefined) => value == null ? 'Not available' : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
const money = (value: number | null | undefined) => value == null ? 'Not available' : `$${number(value)}`;
const stamp = (value: string | null) => value ? new Date(value).toLocaleString() : 'Not verified';

function MetricsTable({ candidate }: { candidate: Candidate }) {
  const fields: [keyof Metrics, string][] = [['net', 'Net P&L'], ['win_rate', 'Win %'], ['profit_factor', 'PF'], ['worst_loss', 'Worst loss'], ['drawdown', 'Drawdown']];
  return <div className="overflow-x-auto">
    <table className="w-full text-xs">
      <caption className="text-left py-2 font-medium">{candidate.name} ({candidate.version})</caption>
      <thead><tr><th className="text-left">Policy</th>{fields.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
      <tbody>{[['Native baseline', candidate.baseline_metrics], ['Candidate', candidate.metrics]].map(([label, metrics]) => (
        <tr key={String(label)}><td>{String(label)}</td>{fields.map(([key]) => <td className="text-center py-1" key={key}>{number((metrics as Metrics | undefined)?.[key])}</td>)}</tr>
      ))}</tbody>
    </table>
    <p className="text-xs mt-2">Paired improvement/trade: {money(candidate.improvement)} | Interval: {candidate.interval ? candidate.interval.map(money).join(' to ') : 'Not available'} | Winners to losses: {number(candidate.winners_to_losses)}</p>
    <p className="text-xs">Candidate pairs: {candidate.pairs ?? 0} | Sessions: {candidate.sessions ?? 0} | Coverage: {candidate.coverage == null ? 'Not available' : `${number(candidate.coverage)}%`} | {candidate.status ?? 'awaiting approval'}</p>
  </div>;
}

function BucketDialog({ bucket, close, scope }: { bucket: Bucket; close: () => void; scope: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [candidate, setCandidate] = useState(bucket.candidates[0]?.id ?? '');
  const [page, setPage] = useState(1);
  const [showTrades, setShowTrades] = useState(false);
  useEffect(() => { dialog.current?.showModal(); }, []);
  const details = useQuery({ queryKey: ['exit-lab-detail', scope, bucket.id, bucket.updated_at], queryFn: ({ signal }) => request<Detail>(`/api/exit-lab/${bucket.id}`, { signal }), staleTime: 60_000 });
  const trades = useQuery({ queryKey: ['exit-lab-trades', scope, bucket.id, bucket.updated_at, page], queryFn: ({ signal }) => request<{ rows: unknown[]; has_more: boolean }>(`/api/exit-lab/${bucket.id}/trades?page=${page}`, { signal }), enabled: showTrades, staleTime: 60_000 });
  const chart = details.data?.chart.filter(row => row.candidate_id === candidate) ?? [];
  return <dialog ref={dialog} onCancel={close} className="card p-5 rounded-xl" style={{ width: 'min(960px, 95vw)', maxHeight: '90vh', color: 'var(--ink)', background: 'var(--surface)', overflow: 'auto' }} aria-labelledby="exit-lab-title">
    <div className="flex items-start justify-between gap-3"><div><h2 id="exit-lab-title" className="text-lg font-semibold">{bucket.ticker} / {bucket.name}</h2><p className="text-xs">{bucket.version} | Execution {bucket.revision.slice(0, 12)} | {bucket.mode}</p></div><button autoFocus className="btn btn-sm btn-ghost" onClick={close} aria-label="Close Exit Lab details">Close</button></div>
    <p className="text-xs mt-3" style={{ color: 'var(--ink-muted)' }}>{bucket.result_kind}. Hypothetical fills are not broker fills. Paper evidence is not live validation.</p>
    {details.isPending && <p role="status">Loading saved evidence...</p>}
    {details.error && <p role="alert">Could not read evidence: {details.error.message}</p>}
    {details.data && <>
      <label className="block text-sm mt-4">Candidate <select className="input ml-2" value={candidate} onChange={event => setCandidate(event.target.value)}>{!bucket.candidates.length && <option value="">No frozen candidate</option>}{bucket.candidates.map(c => <option key={c.id} value={c.id}>{c.name} / {c.version}</option>)}</select></label>
      <h3 className="text-sm font-semibold mt-4">Cumulative paired P&L</h3><p className="text-xs">Identical paired trades for this candidate only. Blue: baseline. Green: candidate.</p>
      {chart.length ? <div style={{ height: 240 }}><ResponsiveContainer width="100%" height="100%"><LineChart data={chart}><CartesianGrid stroke="var(--border)" /><XAxis dataKey="time" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} /><Tooltip /><Line dataKey="baseline" stroke="#3b82f6" dot={false} isAnimationActive={false} /><Line dataKey="candidate" stroke="#16a34a" dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div> : <p className="py-6 text-sm" style={{ color: 'var(--ink-muted)' }}>No complete paired series has been published.</p>}
      {(['rules', 'candidates', 'exclusions', 'evidence', 'history'] as const).map(key => <details key={key} className="border-t py-3" style={{ borderColor: 'var(--border)' }}><summary className="text-sm cursor-pointer capitalize">{key === 'history' ? 'Promotion / rollback history' : key === 'evidence' ? 'Decision evidence' : key === 'candidates' ? 'Exact candidate specifications' : key}</summary><pre className="text-xs whitespace-pre-wrap break-words mt-2">{JSON.stringify(details.data[key], null, 2)}</pre></details>)}
      <button className="btn btn-sm btn-ghost" onClick={() => setShowTrades(!showTrades)}>{showTrades ? 'Hide' : 'Load'} trade-level comparisons</button>
      {showTrades && <div className="mt-3">{trades.isPending && <p>Loading page...</p>}{trades.error && <p role="alert">Could not load trades: {trades.error.message}</p>}{trades.data && <><pre className="text-xs whitespace-pre-wrap break-words">{JSON.stringify(trades.data.rows, null, 2)}</pre><div className="flex gap-3 mt-2"><button className="btn btn-sm" disabled={page === 1} onClick={() => setPage(page-1)}>Previous</button><span>Page {page}</span><button className="btn btn-sm" disabled={!trades.data.has_more} onClick={() => setPage(page+1)}>Next</button></div></>}</div>}
    </>}
  </dialog>;
}

export function ExitLab() {
  const { user } = useAuth();
  const settings = useQuery({ queryKey: ['exit-lab-scope', user?.user_id ?? user?.email], queryFn: () => api.settings.get(), staleTime: 0, refetchInterval: 60_000, enabled: !!user });
  const scope = `${user?.user_id ?? user?.email}:${settings.data?.active_broker_account_id}:${settings.data?.paper_trading}`;
  if (settings.isError) return <p role="alert">Cannot verify the account for Exit Lab: {settings.error.message}</p>;
  if (!settings.data || !user) return <p role="status">Verifying Exit Lab account...</p>;
  return <ScopedExitLab key={scope} scope={scope} ready={!!settings.data && !!user} />;
}

function ScopedExitLab({ scope, ready }: { scope: string; ready: boolean }) {
  const [selected, setSelected] = useState<Bucket | null>(null);
  const [filter, setFilter] = useState('');
  const query = useQuery({ queryKey: ['exit-lab', scope], queryFn: ({ signal }) => request<{ buckets: Bucket[]; capture_state: string }>('/api/exit-lab', { signal }), enabled: ready, staleTime: 60_000, refetchInterval: 60_000, refetchIntervalInBackground: false });
  const rows = (query.data?.buckets ?? []).filter(b => `${b.name} ${b.ticker} ${b.version}`.toLowerCase().includes(filter.toLowerCase()));
  return <section className="space-y-4" aria-label="Exit Lab">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-xl font-semibold">Exit Lab</h1><p className="text-xs" style={{ color: 'var(--ink-muted)' }}>Saved bucket-level evidence. Opening this page never runs a backtest or changes a policy.</p></div><input className="input" aria-label="Filter Exit Lab buckets" placeholder="Ticker or strategy" value={filter} onChange={event => setFilter(event.target.value)} /></header>
    {query.isPending && <p role="status">Loading saved summaries...</p>}{query.error && <p role="alert" className="card p-4">Exit Lab unavailable: {query.error.message}</p>}
    {!query.isPending && !query.error && !rows.length && <div className="card p-6">{query.data?.buckets.length ? 'No matching buckets.' : 'No Exit Lab snapshot published yet. The background publisher must initialize the enabled inventory. No experiments are implied to be running.'}</div>}
    <div className="grid gap-3 xl:grid-cols-2">{rows.map(bucket => <article className="card p-4" key={bucket.id}>
      <button className="w-full text-left" onClick={() => setSelected(bucket)}><div className="flex justify-between gap-3"><h2 className="font-semibold">{bucket.ticker} / {bucket.name}</h2><span className="badge">{bucket.status}</span></div><p className="text-xs mt-1">{bucket.version} | {bucket.mode} | {bucket.revision.slice(0, 12)}</p></button>
      <p className="text-xs mt-2">Baseline: {bucket.baseline}</p><p className="text-xs mt-1" style={{ color: 'var(--ink-muted)' }}>{bucket.result_kind}</p>
      <div className="grid grid-cols-3 gap-2 mt-3 text-xs"><p>Pairs <b>{bucket.pairs}/{bucket.required_pairs ?? '?'}</b></p><p>Sessions <b>{bucket.sessions}/{bucket.required_sessions ?? '?'}</b></p><p>Coverage <b>{bucket.coverage == null ? 'Unknown' : `${number(bucket.coverage)}%`}</b></p></div>
      {bucket.candidates.map(c => <MetricsTable key={c.id} candidate={c} />)}{!bucket.candidates.length && <p className="text-xs mt-3">No approved frozen candidate. Results unavailable.</p>}
      <div className="border-t pt-2 mt-3 text-xs" style={{ borderColor: 'var(--border)' }}><p><b style={{ color: bucket.policy_match === 'MISMATCH' ? 'var(--negative)' : 'var(--ink-muted)' }}>{bucket.policy_match}</b> | Paper: {bucket.paper_policy ?? 'Unverified'} | Live: {bucket.live_policy ?? 'Unverified'}</p><p>Last successful collection: {stamp(bucket.last_collection)}</p><p>Summary published: {stamp(bucket.updated_at)}</p>{bucket.missing.length > 0 && <p style={{ color: 'var(--warning)' }}>Missing: {bucket.missing.join('; ')}</p>}<p className="mt-2 font-medium">{bucket.recommendation}</p><button className="btn btn-sm btn-ghost mt-2" onClick={() => setSelected(bucket)}>Rules, trades and history</button></div>
    </article>)}</div>
    {selected && <BucketDialog key={selected.id} scope={scope} bucket={selected} close={() => setSelected(null)} />}
  </section>;
}
