import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../src/contexts/AuthContext';
import { TradingOverview } from '../src/components/settings/TradingOverview';
import { ResearchPairControl } from '../src/components/research/ResearchPairControl';
import '../src/index.css';
// Isolated fixture: no request is sent to a broker or production API.
window.fetch = async (url, options) => {
  if(String(url).includes('/api/auth/me')) return new Response(JSON.stringify({username:'Fixture admin',is_admin:true}));
  if(String(url).includes('admin-override')) {
    document.getElementById('result')!.textContent = `Mock confirmation: ${options?.body}`;
    return new Response(JSON.stringify({ok:true}));
  }
  return new Response('{}');
};
const strategy:any={strategy_id:'test',display_name:'Trend Continuation',version:'v1',trading_tickers:['SPY','QQQ'],integrity_errors:[]};
const evidence:any={available:true,account_mode:'paper',strategies:[{strategy_id:'test',version:'v1',pairs:['SPY','QQQ'].map((ticker,i)=>({ticker,version:'v1',completed_trades:10,wins:6-i*2,realized_pnl:i?-140:230,profit_factor:i?0.8:1.8,first_entry_date:'2026-10-01',last_exit_date:'2026-10-30'}))}]};
const pair:any={exit_comparison:[{minutes:60,option_results:10,profit_factor:1.3,net_one_contract_pnl:200,win_rate_pct:60,mistimed_quotes_ignored:2}],contract_tests:[{policy:'otm',label:'Closest OTM',profile_version:'research1',option_results:10,option_result_days:5,profit_factor:1.5,net_one_contract_pnl:230}],quote_coverage_pct:80};
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={new QueryClient()}><AuthProvider><main style={{padding:24,maxWidth:1300,margin:'auto'}}><p>LOCAL FIXTURE ONLY</p><TradingOverview strategies={[strategy]} evidence={evidence} loading={false} failed={false} mode="paper" controls={()=> <p>Controls on demand</p>} /><div style={{marginTop:24}}><ResearchPairControl strategyId="test" ticker="SPY" version="v1" name="Test strategy" trading={false} pair={pair}/></div><p id="result"/></main></AuthProvider></QueryClientProvider>);
