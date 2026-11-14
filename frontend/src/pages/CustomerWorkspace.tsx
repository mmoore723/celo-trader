import { Terms } from './Terms';
import { Navigate, useLocation } from 'react-router-dom';
import { learningAccess } from '../lib/access';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../lib/api';
import { TradeChart } from '../components/charts/TradeChart';
import { LearningPortal } from '../components/learning/LearningPortal';

export function CustomerWorkspace() {
  const {user} = useAuth();
  const location=useLocation();
  const learning = learningAccess(user?.access_profile);
  const tab=location.pathname==='/playbooks'?'learn':'watch';
  const [input,setInput] = useState('');
  const [ticker,setTicker] = useState('');
  const bars = useQuery({queryKey:['customer-chart',user?.user_id,ticker],queryFn:()=>api.market.bars(ticker,'5Min',100),enabled:!!ticker && tab==='watch',retry:1});
  if(location.pathname==='/terms')return <Terms viewOnly/>;
  if(location.pathname==='/')return <Navigate to="/trading" replace/>;
  if(location.pathname==='/playbooks'&&learning)return <div className="p-4 md:p-6"><LearningPortal/></div>;
  if(location.pathname!='/trading')return <section className="card p-5"><h1>This tab is not included in your access.</h1><p>Use the sidebar to open the sections available to your tier.</p><a href="#/trading" className="btn btn-primary mt-4">Open charts</a></section>;
  return <div style={{width:'100%',minWidth:0,padding:24}}>
    <h1 className="text-2xl font-semibold mb-4">Live Trading</h1><p className="mb-4">Watch the chart. Your account has viewing access only.</p>
    {tab==='learn' && learning ? <LearningPortal /> : <section className="card p-5">
      <h2 className="text-xl font-semibold">Explore a stock chart</h2><p className="my-3 text-sm">Five-minute stock candles from the existing Yahoo Finance chart source. Data may be delayed. This is not the bot’s execution feed. Bot-thinking and AI pattern callouts are not included in this preview.</p>
      <form className="flex gap-2 mb-4" onSubmit={e=>{e.preventDefault();if(/^[A-Z][A-Z0-9.-]{0,9}$/.test(input.trim().toUpperCase()))setTicker(input.trim().toUpperCase());}}><label>Stock ticker <input className="input" value={input} maxLength={10} placeholder="Enter ticker" onChange={e=>setInput(e.target.value)} required pattern="[A-Za-z][A-Za-z0-9.\-]{0,9}" /></label><button className="btn btn-primary self-end" type="submit">Show chart</button></form>
      {!ticker ? <p>Enter a stock ticker to open its chart. This does not add it to the trading or research universe.</p> : bars.isPending ? <p>Loading {ticker}...</p> : bars.isError ? <p role="alert">No chart data available for {ticker}. <button className="btn btn-ghost" onClick={()=>bars.refetch()}>Try again</button></p> : <><p className="text-sm mb-2">{ticker} · Latest candle timestamp: {bars.data?.at(-1)?.time ?? 'Unavailable'}. The last candle may still be forming.</p><TradeChart ticker={ticker} bars={bars.data??[]} showVwap={false} showVwapBands={false} showOR={false} showSwings={false} showStructure={false} showRsi={false} showMacd={false} viewportKey={`customer:${ticker}`} height={430}/></>}
    </section>}
  </div>;
}
