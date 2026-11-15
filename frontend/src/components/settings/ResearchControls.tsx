import {useEffect, useState} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {api, type AppSettings} from '../../lib/api';
import {useAuth} from '../../contexts/AuthContext';
import {AdminStrategyControls} from './AdminStrategyControls';
import {ResearchTargetTickers} from './StrategyRemoval';
import {TestedStrategies} from './TestedStrategies';
import {StrategyRecommendations} from './StrategyRecommendations';
export function ResearchControls(){
 const {user}=useAuth();const qc=useQueryClient();const admin=!!user?.is_admin;
 const {data}=useQuery({queryKey:['settings'],queryFn:api.settings.get,enabled:admin});
 const {data:catalog}=useQuery({queryKey:['strategy-catalog'],queryFn:api.settings.strategies,enabled:admin});
 const {data:matrix}=useQuery({queryKey:['strategy-research-matrix',user?.user_id],queryFn:()=>api.strategyHealth.researchMatrix(90),enabled:admin});
 const {data:recommendations,isError:recommendationsFailed}=useQuery({queryKey:['strategy-recommendations',user?.user_id],queryFn:api.settings.recommendations,enabled:admin});
 const [draft,setDraft]=useState<Partial<AppSettings>>({});const [message,setMessage]=useState('');const [busy,setBusy]=useState(false);
 useEffect(()=>{setDraft({});},[data]);
 if(!admin)return null;
 async function save(){if(!data)return;setBusy(true);setMessage('');try{await api.settings.save({...data,...draft});setDraft({});await qc.invalidateQueries({queryKey:['settings']});setMessage('Research settings saved.');}catch(e){setMessage(e instanceof Error?e.message:'Could not save research settings.');}finally{setBusy(false);}}
 return <div className="space-y-4"><h2 className="text-xl font-semibold">Research controls</h2><p>Admin tools for testing strategies and reviewing new ticker approvals.</p><AdminStrategyControls/><ResearchTargetTickers/>
 {recommendationsFailed ? <p role="alert">Recommendations could not load. Refresh this page to try again.</p> : !recommendations ? <p role="status">Loading recommendations...</p> : <StrategyRecommendations recommendations={recommendations.recommendations} onDecision={async(item,decision)=>{await api.settings.decidePair(item,decision);await Promise.all(['strategy-recommendations','strategy-catalog','settings'].map(key=>qc.invalidateQueries({queryKey:[key]})));}}/>}
 <section className="card p-4 space-y-3"><h3 className="font-semibold">Background research</h3>{catalog?.strategies.filter(row=>row.observation_only&&!row.removed).map(row=><label className="block" key={row.strategy_id}><input type="checkbox" checked={!!(row.setting_key in draft?draft[row.setting_key]:data?.[row.setting_key])} onChange={e=>setDraft({...draft,[row.setting_key]:e.target.checked})}/> {row.display_name}</label>)}
 <TestedStrategies researchIds={draft.research_strategy_ids??data?.research_strategy_ids??[]} onResearchIdsChange={ids=>setDraft({...draft,research_strategy_ids:ids})} researchMatrix={matrix}/><button className="btn btn-primary" disabled={!data||busy||!Object.keys(draft).length} onClick={save}>{busy?'Saving...':'Save research settings'}</button>{message&&<p role="status">{message}</p>}</section></div>;
}
