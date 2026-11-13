import {createRoot} from 'react-dom/client';
import {LiveActivityFeed} from '../src/components/LiveActivityFeed';
import {useBotStore} from '../src/store/bot';
import '../src/index.css';
for(let i=0;i<12;i++) useBotStore.getState().addLog({ts:'2026-11-12T20:15:00Z',level:'INFO',ticker:'AMZN',strategy_id:'V2_VWAP_PULLBACK',message:'VWAP touch checked. Waiting for rejection close.',conditions:[{name:'VWAP touch',passed:true,reason:'Recorded touch passed.'},{name:'Rejection',status:'evaluating',reason:'Waiting for the next close.'}]});
createRoot(document.getElementById('root')!).render(<div style={{maxWidth:620,margin:'20px auto'}}><LiveActivityFeed/><button onClick={()=>useBotStore.getState().addLog({level:'INFO',message:'New unique update',ticker:'SPY'})}>Add update</button><button onClick={()=>document.documentElement.classList.toggle('dark')}>Theme</button></div>);
