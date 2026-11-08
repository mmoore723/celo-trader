import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { FastCaptureStatus } from '../components/FastCaptureStatus';

type Row = { ticker: string; expected_minutes: number; captured_minutes: number; coverage_pct: number | null; missing_minutes: string[]; first_bar: string | null; last_bar: string | null; quote_minutes: number; fresh_quote_minutes: number; last_quote_at: string | null; listed_expirations: number; captured_expirations: number; contracts_discovered: number; contracts_with_fresh_snapshot: number; pending_expirations: string[]; oldest_chain_at: string | null; errors: { kind: string; expiration: string; reason: string }[] };
type CadenceRow = Row & { max_option_refresh_gap_seconds?: number | null; oldest_option_refresh_age_seconds?: number | null; option_refresh_cadence?: { expiration: string; samples: number; max_gap_seconds: number | null; max_request_seconds: number; age_seconds: number }[] };
type Report = { status: string; day?: string; heartbeat_at?: string; worker_stale: boolean; session_start?: string; session_end?: string; tickers: CadenceRow[]; limitations?: string[]; error?: string };
const stamp = (v?: string | null) => v ? new Date(v).toLocaleString() : 'Not received';
const duration = (v?: number | null) => v == null ? 'Not measured' : `${Math.round(v)} seconds`;

export function CaptureCoverage() {
  const { user } = useAuth();
  const [selected, setSelected] = useState('');
  const [page, setPage] = useState(1);
  const report = useQuery({ queryKey: ['session-capture', user?.user_id ?? user?.email], queryFn: () => request<Report>('/api/session-capture'), refetchInterval: 30_000, staleTime: 15_000 });
  const detail = useQuery({ queryKey: ['session-contracts', user?.user_id ?? user?.email, report.data?.day, selected, page], queryFn: () => request<{ rows: Record<string, unknown>[]; has_more: boolean }>(`/api/session-capture/contracts?ticker=${encodeURIComponent(selected)}&day=${report.data?.day}&page=${page}`), enabled: !!selected && !!report.data?.day, staleTime: 30_000 });
  if (report.isPending) return <p role="status">Loading saved capture report...</p>;
  if (report.error) return <p role="alert">Capture report unavailable: {report.error.message}</p>;
  const data = report.data!;
  return <section className="card p-4 space-y-3">
    <FastCaptureStatus />
    <h2 className="text-lg font-semibold">Full-session data coverage</h2>
    <p className="text-sm">{data.tickers.length} approved tickers. Independent of trades. Market observations are shared research data, not paper or live fills.</p>
    <p className="text-sm" role="status">Worker: {data.worker_stale ? 'STALE / NOT VERIFIED' : data.status.replaceAll('_', ' ')}. Last report: {stamp(data.heartbeat_at)}</p>
    {data.error && <p role="alert">{data.error}</p>}
    <p className="text-xs">Session: {stamp(data.session_start)} to {stamp(data.session_end)}. Coverage is elapsed completed stock minutes, not exchange tick coverage.</p>
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><th>Ticker</th><th>Stock minutes</th><th>Coverage</th><th>Fresh quote minutes</th><th>Option expirations received</th><th>Contracts discovered</th></tr></thead><tbody>{data.tickers.map(r => <tr key={r.ticker} className="border-t"><td><button className="btn btn-sm btn-ghost" onClick={() => { setSelected(selected === r.ticker ? '' : r.ticker); setPage(1); }}>{r.ticker}</button></td><td className="text-center">{r.captured_minutes}/{r.expected_minutes}</td><td className="text-center">{r.coverage_pct == null ? 'No elapsed session' : `${r.coverage_pct}%`}</td><td className="text-center">{r.fresh_quote_minutes}</td><td className="text-center">{r.captured_expirations}/{r.listed_expirations}{!r.listed_expirations && ' (not verified)'}</td><td className="text-center">{r.contracts_discovered}</td></tr>)}</tbody></table></div>
    {data.tickers.filter(r => r.ticker === selected).map(r => <div key={r.ticker} className="border rounded p-3 space-y-2">
      <h3 className="font-semibold">{r.ticker}: exact coverage</h3><p className="text-xs">First bar: {stamp(r.first_bar)}. Last bar: {stamp(r.last_bar)}. Last stock snapshot: {stamp(r.last_quote_at)}.</p>
      <p className="text-xs">{r.contracts_with_fresh_snapshot}/{r.contracts_discovered} discovered contracts had at least one fresh snapshot. This does not mean continuous option coverage. Oldest expiration refresh: {stamp(r.oldest_chain_at)}.</p>
      <p className="text-xs">Pending expirations: {r.pending_expirations.join(', ') || 'None listed'}</p>
      <p className="text-xs">Longest observed option refresh gap: {duration(r.max_option_refresh_gap_seconds)}. Oldest refresh age at report time: {duration(r.oldest_option_refresh_age_seconds)}. Receipt timing does not prove fresh contract prices.</p>
      <details><summary>Option refresh timing by expiration</summary>
        {!r.option_refresh_cadence?.length ? <p className="text-xs">No timing samples yet. This is not zero delay.</p> :
          <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr><th>Expiration</th><th>Responses</th><th>Longest gap</th><th>Longest request</th><th>Age at report</th></tr></thead><tbody>{r.option_refresh_cadence.map(c => <tr key={c.expiration}><td>{c.expiration}</td><td>{c.samples}</td><td>{duration(c.max_gap_seconds)}</td><td>{duration(c.max_request_seconds)}</td><td>{duration(c.age_seconds)}</td></tr>)}</tbody></table></div>}
      </details>
      <details><summary>{r.missing_minutes.length} unresolved stock minutes</summary><p className="text-xs break-words">{r.missing_minutes.join(', ') || 'None'}</p></details>
      <p className="text-xs">{r.errors.map(e => `${e.kind} ${e.expiration}: ${e.reason}`).join('; ') || 'No recorded request failures'}</p>
      {detail.isPending && <p>Loading contract inventory...</p>}{detail.error && <p role="alert">{detail.error.message}</p>}
      {detail.data && <><details><summary>Contract inventory and quote status (100 per page)</summary><pre className="text-xs whitespace-pre-wrap break-words">{JSON.stringify(detail.data.rows, null, 2)}</pre></details><button className="btn btn-sm" disabled={page === 1} onClick={() => setPage(page-1)}>Previous</button> Page {page} <button className="btn btn-sm" disabled={!detail.data.has_more} onClick={() => setPage(page+1)}>Next</button></>}
    </div>)}
    <details><summary className="text-sm">What is and is not captured</summary><ul className="text-xs list-disc pl-5">{data.limitations?.map(t => <li key={t}>{t}</li>)}</ul></details>
  </section>;
}
