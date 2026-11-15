import { StrategyConfiguration } from './StrategyConfiguration';
import { useState, type ReactNode } from 'react';
import type { ClosedTradeEvidence, ReviewedStrategyCatalogEntry } from '../../lib/api';
import { groupStrategies } from '../../lib/strategyIdentity.js';
export function TradingOverview({ strategies, mode, controls, loading }: {
 strategies: ReviewedStrategyCatalogEntry[]; evidence?: ClosedTradeEvidence; loading:boolean; failed:boolean; mode:string; controls:(strategy:ReviewedStrategyCatalogEntry)=>ReactNode;
}) {
 const [search,setSearch]=useState('');const [selected,setSelected]=useState('');
 const groups=groupStrategies(strategies.filter(s=>(s.tickers?.length??0)+(s.trading_tickers?.length??0)>0)) as {name:string;strategies:ReviewedStrategyCatalogEntry[]}[];
 const tickers=(s:ReviewedStrategyCatalogEntry)=>Array.from(new Set([...(s.tickers??[]),...(s.trading_tickers??[])]));
 const visible=groups.filter(g=>`${g.name} ${g.strategies.flatMap(tickers).join(' ')}`.toLowerCase().includes(search.toLowerCase()));
 return <div className="space-y-4">
 <header className="flex flex-wrap justify-between items-center gap-3"><div><h2 className="text-xl font-semibold">Your strategies</h2><p className="text-sm text-ink-muted">Choose a ticker to see its entry checks, position size and exit rules.</p></div><span className="badge">{groups.length} strategies · {mode.toUpperCase()}</span></header>
 <label className="block text-sm">Find a strategy or ticker<input className="input w-full mt-1" placeholder="Search strategies or tickers" value={search} onChange={e=>setSearch(e.target.value)}/></label>
 {loading?<p role="status">Loading your strategies...</p>:!groups.length?<p>No strategies are available for this account yet.</p>:!visible.length?<p>No matching strategies.</p>:null}
 <div className="space-y-3">{visible.map(group=><section className="card p-4 sm:p-5 min-w-0" aria-label={`${group.name} strategy`} key={group.name}><h3 className="text-lg font-semibold">{group.name}</h3><div className="mt-3 space-y-2">{group.strategies.map(strategy=><div key={`${strategy.strategy_id}:${strategy.version}`}><div className="flex flex-wrap gap-2">{tickers(strategy).map(ticker=>{
 const key=`${strategy.strategy_id}:${strategy.version}:${ticker}`;
 const paused=strategy.automatic_pauses?.some(item=>item.ticker===ticker);
 const state=paused?'Paused':strategy.integrity_errors.length?'Needs attention':strategy.enabled&&strategy.trading_tickers?.includes(ticker)?'Enabled':'Off';
 return <button type="button" key={key} className={`btn ${selected===key?'btn-primary':'btn-ghost'}`} aria-expanded={selected===key} aria-controls={`settings-${key}`} onClick={()=>setSelected(selected===key?'':key)}><strong>{ticker}</strong><span className="text-xs">{state}</span><span className="text-xs">Settings</span></button>;
 })}</div>{tickers(strategy).map(ticker=>{const key=`${strategy.strategy_id}:${strategy.version}:${ticker}`;if(selected!==key)return null;return <section key={key} id={`settings-${key}`} aria-label={`${ticker} ${group.name} settings`} className="mt-3 rounded-lg border p-4 space-y-4" style={{borderColor:'var(--border)'}}><div className="flex justify-between gap-3"><div><h4 className="font-semibold">{ticker} settings</h4><p className="text-xs text-ink-muted">{group.name} · Version {strategy.version} · {mode} account</p></div><button type="button" className="btn btn-ghost" onClick={()=>setSelected('')}>Close</button></div>{controls(strategy)}{strategy.automatic_pauses?.filter(item=>item.ticker===ticker).map(item=><p role="status" key={item.ticker}>New entries are automatically paused after {item.completed_trades} closed trades. Turning the switch on does not override this pause.</p>)}<StrategyConfiguration key={key} strategy={strategy.strategy_id} ticker={ticker} version={strategy.version} embedded/></section>;})}</div>)}</div></section>)}</div></div>;
}
