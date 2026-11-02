import { useState, type ReactNode } from 'react';
import type { ClosedTradeEvidence, ReviewedStrategyCatalogEntry } from '../../lib/api';
import { strategyName } from '../../lib/strategyIdentity.js';

const money = (value: number | null | undefined) => value == null ? 'Not available' : value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

export function TradingOverview({ strategies, evidence, loading, failed, mode, controls }: {
  strategies: ReviewedStrategyCatalogEntry[]; evidence?: ClosedTradeEvidence;
  loading: boolean; failed: boolean; mode: string;
  controls: (strategy: ReviewedStrategyCatalogEntry) => ReactNode;
}) {
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const rows = strategies.flatMap(strategy => (strategy.trading_tickers ?? []).map(ticker => {
    const record = !failed && evidence?.available && evidence.account_mode === mode
      ? evidence.strategies.find(item => item.strategy_id === strategy.strategy_id && item.version === strategy.version)
        ?.pairs.find(pair => pair.ticker === ticker && pair.version === strategy.version) : undefined;
    const paused = strategy.automatic_pauses?.some(item => item.ticker === ticker);
    return { strategy, ticker, record, paused, id: `${strategy.strategy_id}:${strategy.version}:${ticker}` };
  }));
  const visible = rows.filter(row => `${row.ticker} ${row.strategy.display_name} ${row.strategy.version}`.toLowerCase().includes(search.toLowerCase()));
  const chosen = visible.find(row => row.id === selected) ?? visible[0];
  const record = chosen?.record;
  const count = record?.completed_trades ?? 0;
  const measured = !!record && count > 0;
  const max = Math.max(1, ...visible.map(row => Math.abs(row.record?.realized_pnl ?? 0)));
  return <div className="space-y-4">
    <div className="flex flex-wrap justify-between items-center gap-3">
      <div><h3 className="text-xl font-semibold">Trading now</h3><p className="text-sm" style={{ color: 'var(--ink-muted)' }}>{mode.toUpperCase()} account · Saved permissions, not open positions</p></div>
      <div className="flex gap-3 text-sm"><span className="badge badge-green">{rows.filter(row => !row.paused && !row.strategy.integrity_errors.length).length} enabled pairs</span><span className="badge">{strategies.length} strategies</span></div>
    </div>
    <p className="text-xs" style={{ color: 'var(--ink-muted)' }}>Journal results only. Each ticker and code version stays separate. An enabled pair still needs a valid signal and passing account safety checks.</p>
    {failed && <p role="alert">Trade results failed to load. Permissions are shown, performance is unavailable.</p>}
    {loading && <p role="status">Loading saved account results...</p>}
    <label className="block text-sm">Find a strategy or ticker<input className="input w-full mt-1" placeholder="Search strategies, tickers or versions" value={search} onChange={event => setSearch(event.target.value)} /></label>
    {!rows.length ? <div className="card p-5">No enabled trading pairs. Use Research / off to review strategies.</div> : <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,1fr)]">
      <section className="card overflow-hidden" aria-label="Enabled strategy pairs">
        <div className="overflow-x-auto"><table className="w-full text-sm text-left">
          <thead><tr style={{ background: 'var(--surface-raised)' }}>{['Strategy / ticker', 'State', 'Closed', 'Net P&L'].map(label => <th className="p-3" key={label}>{label}</th>)}</tr></thead>
          <tbody>{visible.map(row => <tr key={row.id} style={{ borderTop: '1px solid var(--border)', background: chosen?.id === row.id ? 'color-mix(in srgb, var(--accent) 8%, var(--surface))' : undefined }}>
            <td className="p-3"><button type="button" className="text-left" aria-pressed={chosen?.id === row.id} onClick={() => setSelected(row.id)}><strong>{row.ticker}</strong><span className="block">{strategyName(row.strategy.display_name)}</span><span className="text-xs" style={{ color: 'var(--ink-muted)' }}>{row.strategy.version}</span></button></td>
            <td className="p-3"><span className={`badge ${row.paused || row.strategy.integrity_errors.length ? '' : 'badge-green'}`}>{row.paused ? 'Paused' : row.strategy.integrity_errors.length ? 'Code blocked' : 'Enabled'}</span></td>
            <td className="p-3">{row.record?.completed_trades ?? 'Unavailable'}</td>
            <td className="p-3 whitespace-nowrap" style={{ color: (row.record?.realized_pnl ?? 0) < 0 ? 'var(--negative)' : 'var(--ink)' }}>{!row.record ? 'Unavailable' : row.record.completed_trades ? money(row.record.realized_pnl) : 'No results'}</td>
          </tr>)}</tbody>
        </table></div>
        {!visible.length && <p className="p-4">No matching pairs.</p>}
      </section>
      {chosen && <section className="card p-4 space-y-4" aria-label="Selected pair performance">
        <div><h4 className="font-semibold text-lg">{chosen.ticker} · {strategyName(chosen.strategy.display_name)}</h4><p className="text-xs">{chosen.strategy.version} · {mode} journal</p></div>
        <div className="grid grid-cols-2 gap-3">
          {[
            ['Realized net P&L', measured ? money(record?.realized_pnl) : 'No results'],
            ['Closed trades', record ? String(count) : 'Unavailable'],
            ['Win rate', measured ? `${(100 * record!.wins / count).toFixed(1)}%` : 'Not available'],
            ['Profit factor', measured && record?.profit_factor != null ? record.profit_factor === 'infinite' ? 'No gross losses' : record.profit_factor.toFixed(2) : 'Not available'],
          ].map(([label, value]) => <div key={label} className="rounded-lg p-3" style={{ background: 'var(--surface-raised)' }}><span className="text-xs block" style={{ color: 'var(--ink-muted)' }}>{label}</span><strong className="text-lg">{value}</strong></div>)}
        </div>
        {measured && <figure aria-label="Closed trade outcomes"><figcaption className="text-xs mb-2">Wins versus other closed trades</figcaption><div className="flex h-4 rounded overflow-hidden" aria-hidden="true"><div style={{ width: `${100 * record!.wins / count}%`, background: 'var(--positive)' }} /><div style={{ flex: 1, background: 'var(--border)' }} /></div><p className="text-xs mt-2">{record!.wins} wins · {count - record!.wins} losses or breakeven</p></figure>}
        <p className="text-xs" style={{ color: 'var(--ink-muted)' }}>{record?.first_entry_date && record.last_exit_date ? `Recorded period: ${record.first_entry_date} to ${record.last_exit_date}` : 'No dated closed-trade sample for this exact version.'} No research simulations included.</p>
        <details><summary className="cursor-pointer text-sm font-medium">Controls, audit and evidence</summary><div className="mt-3">{controls(chosen.strategy)}</div></details>
      </section>}
    </div>}
    {!!visible.length && <figure className="card p-4" aria-label="Realized P&L by separate strategy bucket">
      <figcaption className="font-semibold mb-1">Realized P&L by pair</figcaption><p className="text-xs mb-4" style={{ color: 'var(--ink-muted)' }}>Separate samples and date ranges. Not a pooled ranking or an equity curve.</p>
      <div className="space-y-3">{visible.map(row => <div key={row.id} className="grid grid-cols-[minmax(8rem,1fr)_2fr_auto] gap-3 items-center text-xs">
        <span>{row.ticker} · {strategyName(row.strategy.display_name)}<span className="block" style={{ color: 'var(--ink-muted)' }}>{row.strategy.version}</span></span>
        <div className="relative h-5" style={{ background: 'var(--surface-raised)' }} aria-hidden="true"><div className="absolute inset-y-0" style={{ left: '50%', width: 1, background: 'var(--ink-muted)' }} /><div className="absolute inset-y-1 rounded" style={{ left: (row.record?.realized_pnl ?? 0) < 0 ? `${50 - Math.abs(row.record?.realized_pnl ?? 0) / max * 50}%` : '50%', width: `${Math.abs(row.record?.realized_pnl ?? 0) / max * 50}%`, background: (row.record?.realized_pnl ?? 0) < 0 ? 'var(--negative)' : 'var(--positive)' }} /></div>
        <span>{!row.record ? 'Unavailable' : row.record.completed_trades ? money(row.record.realized_pnl) : 'No results'}</span>
      </div>)}</div>
    </figure>}
  </div>;
}
