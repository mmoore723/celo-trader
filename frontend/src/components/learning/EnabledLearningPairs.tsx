import { useState } from 'react';
import type { ReviewedStrategyCatalogEntry } from '../../lib/api';
import { PairLearning } from './PairLearning';
import { learningFamily } from '../../lib/learningFamilies';

export function EnabledLearningPairs({strategies}: {strategies: ReviewedStrategyCatalogEntry[]}) {
  const [family, setFamily] = useState('');
  const [variant, setVariant] = useState('');
  const enabled = strategies.filter(s => s.enabled && (s.trading_tickers ?? []).length);
  const families = [...new Set(enabled.map(learningFamily))].sort();
  const activeFamily = families.includes(family) ? family : families.find(name => name === 'Opening-Range Breakout (ORB)') ?? families[0];
  const variants = enabled.filter(s => learningFamily(s) === activeFamily);
  const selected = variants.find(s => `${s.strategy_id}:${s.version}` === variant) ?? variants[0];
  return <section className="space-y-4" aria-label="Strategy school">
    <div className="card p-4 space-y-3">
      <h2 className="font-semibold text-xl">Learn a strategy</h2>
      <p className="text-sm">Pick a course. Follow the chart. Practice the decisions.</p>
      {!selected ? <p>No enabled strategies are available.</p> : <>
        <label className="block text-sm">Strategy<select aria-label="Strategy family" className="input w-full mt-1" value={activeFamily} onChange={e => {setFamily(e.target.value); setVariant('');}}>{families.map(name => <option key={name}>{name}</option>)}</select></label>
        {variants.length > 1 ? <label className="block text-sm">Variation and version<select aria-label="Strategy variation" className="input w-full mt-1" value={`${selected.strategy_id}:${selected.version}`} onChange={e => setVariant(e.target.value)}>{variants.map(s => <option key={s.strategy_id} value={`${s.strategy_id}:${s.version}`}>{s.display_name} · {s.version}</option>)}</select></label> : <p className="text-sm">{selected.display_name} · Version {selected.version}</p>}
        <p className="text-xs">Examples: {(selected.trading_tickers ?? []).join(', ')}</p>
      </>}
    </div>
    {selected && <PairLearning key={`${selected.strategy_id}:${selected.version}`} strategyCatalog={strategies} selection={{strategy:selected.strategy_id,version:selected.version,ticker:selected.trading_tickers![0]}} />}
  </section>;
}
