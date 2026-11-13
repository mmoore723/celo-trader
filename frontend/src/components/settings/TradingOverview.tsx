import { useState, type ReactNode } from 'react';
import type { ClosedTradeEvidence, ReviewedStrategyCatalogEntry } from '../../lib/api';
import { groupStrategies } from '../../lib/strategyIdentity.js';
import { Link } from 'react-router-dom';
import { learningLink } from '../../lib/learningLinks';

const money = (value: number | null | undefined) => value == null ? 'Unavailable' : value.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

export function TradingOverview({ strategies, evidence, loading, failed, mode, controls }: {
  strategies: ReviewedStrategyCatalogEntry[]; evidence?: ClosedTradeEvidence;
  loading: boolean; failed: boolean; mode: string;
  controls: (strategy: ReviewedStrategyCatalogEntry) => ReactNode;
}) {
  const [search, setSearch] = useState('');
  const groups = groupStrategies(strategies) as { name: string; strategies: ReviewedStrategyCatalogEntry[] }[];
  const visible = groups.filter(group => `${group.name} ${group.strategies.flatMap(s => s.trading_tickers ?? []).join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="space-y-4">
    <div className="flex flex-wrap justify-between items-center gap-3">
      <div><h3 className="text-xl font-semibold">Your strategies</h3><p className="text-sm text-ink-muted">One strategy. Its tickers underneath.</p></div>
      <span className="badge">{groups.length} strategies · {mode.toUpperCase()}</span>
    </div>
    {failed && <p role="alert">Trade results could not load. Your saved strategy settings are still shown.</p>}
    {loading && <p role="status">Loading saved account results...</p>}
    <label className="block text-sm">Find a strategy or ticker<input className="input w-full mt-1" placeholder="Search strategies or tickers" value={search} onChange={event => setSearch(event.target.value)} /></label>
    {!groups.length && <div className="card p-5">No enabled trading pairs. Use Research / off to review strategies.</div>}
    {!!groups.length && !visible.length && <p>No matching strategies.</p>}
    <div className="grid gap-4 lg:grid-cols-2 items-start">
      {visible.map(group => <section className="card p-4 min-w-0" aria-label={`${group.name} strategy`} key={group.name}>
        <h4 className="text-lg font-semibold">{group.name}</h4>
        <p className="text-xs text-ink-muted mt-1">Trading on {Array.from(new Set(group.strategies.flatMap(s => s.trading_tickers ?? []))).join(', ')}</p>
        <div className="mt-4 ml-2 pl-3 space-y-2" style={{ borderLeft: '2px solid var(--border)' }}>
          {group.strategies.flatMap(strategy => (strategy.trading_tickers ?? []).map(ticker => {
            const record = !failed && evidence?.available && evidence.account_mode === mode
              ? evidence.strategies.find(item => item.strategy_id === strategy.strategy_id && item.version === strategy.version)
                ?.pairs.find(pair => pair.ticker === ticker && pair.version === strategy.version) : undefined;
            const count = record?.completed_trades ?? 0;
            const paused = strategy.automatic_pauses?.some(item => item.ticker === ticker);
            return <details key={`${strategy.strategy_id}:${strategy.version}:${ticker}`} className="rounded-lg border p-3" style={{ borderColor: 'var(--border)' }}>
              <summary className="cursor-pointer text-sm"><strong>{ticker}</strong><span className={`badge ml-3 ${paused || strategy.integrity_errors.length ? '' : 'badge-green'}`}>{paused ? 'Paused' : strategy.integrity_errors.length ? 'Needs attention' : 'Enabled'}</span><span className="ml-3 text-xs text-ink-muted">Ticker details</span></summary>
              <div className="pt-3 space-y-3 text-sm">
                <p className="text-xs text-ink-muted">Version {strategy.version} · {mode} account</p>
                <div className="grid grid-cols-2 gap-2">
                  <div><span className="text-xs text-ink-muted block">Closed trades</span>{record ? count : 'Unavailable'}</div>
                  <div><span className="text-xs text-ink-muted block">Recorded P&amp;L</span>{!record ? 'Unavailable' : count ? money(record.realized_pnl) : 'No results'}</div>
                  <div><span className="text-xs text-ink-muted block">Win rate</span>{count ? `${(100 * record!.wins / count).toFixed(1)}%` : 'Not available'}</div>
                  <div><span className="text-xs text-ink-muted block">Profit factor</span>{count && record?.profit_factor != null ? record.profit_factor === 'infinite' ? 'No gross losses' : record.profit_factor.toFixed(2) : 'Not available'}</div>
                </div>
                <p className="text-xs text-ink-muted">{record?.first_entry_date && record.last_exit_date ? `Recorded period: ${record.first_entry_date} to ${record.last_exit_date}.` : 'No dated results for this version.'} Journal results only. Results stay separate for each ticker and version.</p>
                <nav className="flex gap-2 flex-wrap" aria-label={`Learn ${group.name} for ${ticker}`}>
                  {['Lesson','Reference','Practice'].map(label => <Link className="btn btn-sm btn-ghost" key={label} to={learningLink(strategy.strategy_id,ticker,strategy.version,label.toLowerCase())}>{label}</Link>)}
                </nav>
              </div>
            </details>;
          }))}
        </div>
        <details className="mt-4 text-sm"><summary className="cursor-pointer font-medium">Manage this strategy</summary>
          <p className="text-xs text-ink-muted my-2">Each setting below applies to the tickers shown with it.</p>
          {group.strategies.map(strategy => <div key={`${strategy.strategy_id}:${strategy.version}`} className="mt-3">
            <p className="text-xs font-semibold mb-2">{(strategy.trading_tickers ?? []).join(', ')} · Version {strategy.version}</p>
            {controls(strategy)}
          </div>)}
        </details>
      </section>)}
    </div>
  </div>;
}
