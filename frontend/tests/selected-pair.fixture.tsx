import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../src/contexts/AuthContext';
import { ResearchPairControl } from '../src/components/research/ResearchPairControl';
import '../src/index.css';
window.fetch = async (url, options) => {
  if (String(url).includes('/api/auth/me')) return new Response(JSON.stringify({username:'Fixture',is_admin:true}));
  if (String(url).includes('admin-override')) {
    document.getElementById('result')!.textContent = String(options?.body);
    return new Response(JSON.stringify({ok:true}));
  }
  return new Response('{}');
};
const pair:any={exit_comparison:[{minutes:90,option_results:35,profit_factor:3.54,net_one_contract_pnl:2473.5,win_rate_pct:48.6,mistimed_quotes_ignored:0}],contract_tests:[{policy:'closest_otm_150_1000',label:'Closest OTM $150-$1,000',profile_version:'research_contracts_v1',option_results:35,option_result_days:8,profit_factor:3.5,net_one_contract_pnl:2443.5}],quote_coverage_pct:50};
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={new QueryClient()}><AuthProvider><main style={{padding:24}}><h1>LOCAL MOCK ONLY. No production writes.</h1><ResearchPairControl strategyId="V2_AFTERNOON_REVERSAL" ticker="QQQ" version="research.1" name="Afternoon Reversal" trading={false} pair={pair}/><pre id="result"/></main></AuthProvider></QueryClientProvider>);
