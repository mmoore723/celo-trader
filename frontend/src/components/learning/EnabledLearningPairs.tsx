import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { ReviewedStrategyCatalogEntry } from '../../lib/api';
import { learningLink } from '../../lib/learningLinks';

export function EnabledLearningPairs({strategies}: {strategies: ReviewedStrategyCatalogEntry[]}) {
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState('');
  const pairs = strategies.filter(s => s.enabled).flatMap(s => (s.trading_tickers ?? []).map(ticker => ({...s,ticker,key:`${s.strategy_id}:${ticker}:${s.version}`})));
  const visible = pairs.filter(p => `${p.ticker} ${p.display_name}`.toLowerCase().includes(search.toLowerCase()));
  const selected = visible.find(p => p.key === selection) ?? visible[0];
  return <section className="card p-4 space-y-3" aria-label="Your enabled pairs">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">Your enabled pairs</h2><span className="text-xs">{pairs.length} pairs</span></div>
    <input aria-label="Find a learning pair" className="input w-full" placeholder="Find a ticker or strategy" value={search} onChange={e => setSearch(e.target.value)} />
    {!selected ? <p className="text-sm">No matching enabled pairs.</p> : <>
      <label className="block text-sm">Choose a pair<select aria-label="Learning pair" className="input w-full mt-1" value={selected.key} onChange={e => setSelection(e.target.value)}>{visible.map(p => <option key={p.key} value={p.key}>{p.ticker} · {p.display_name} · {p.version}</option>)}</select></label>
      <div className="flex flex-wrap items-center gap-2">{['lesson','reference','practice'].map(view => <Link className={`btn btn-sm ${view === 'lesson' ? 'btn-primary' : 'btn-ghost'}`} key={view} to={learningLink(selected.strategy_id,selected.ticker,selected.version,view)}>{view === 'lesson' ? 'Open lesson' : view === 'reference' ? 'Quick reference' : 'Practice'}</Link>)}</div>
      <p className="text-xs" style={{color:'var(--ink-muted)'}}>One pair at a time. Practice separates your trades, scanner observations and teaching examples.</p>
    </>}
  </section>;
}
