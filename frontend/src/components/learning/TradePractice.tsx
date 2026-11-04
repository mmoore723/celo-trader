import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';

type Exercise = {id:string; source:string; title:string; facts:string; question:string; choices:string[]; answer:string; explanation:string; synthetic:boolean};
type Library = {actual:Exercise[]; samples:Exercise[]; exclusions:Record<string,number>; mode:string; source:string};

function ExerciseCard({item}: {item:Exercise}) {
  const [answer,setAnswer] = useState('');
  return <article className="card p-4 space-y-3">
    <p className="text-xs font-semibold" style={{color:'var(--accent)'}}>{item.source}</p>
    <h3 className="font-semibold">{item.title}</h3><p className="text-sm">{item.facts}</p>
    <p className="text-sm font-semibold">{item.question}</p>
    <div className="flex flex-wrap gap-2">{item.choices.map(choice => <button key={choice} disabled={Boolean(answer)} className="btn btn-sm btn-ghost" onClick={() => setAnswer(choice)}>{choice}</button>)}</div>
    {answer && <p role="status" className="text-sm">{answer === item.answer ? 'Correct. ' : `Answer: ${item.answer}. `}{item.explanation}</p>}
  </article>;
}

export function TradePractice({strategy,ticker,version}: {strategy:string;ticker:string;version:string}) {
  const {user}=useAuth();
  const [index,setIndex]=useState(0);
  const {data,isPending,isError,refetch}=useQuery({queryKey:['trade-practice',user?.user_id,strategy,ticker,version],
    queryFn:()=>request<Library>(`/api/learning/trade-practice?${new URLSearchParams({strategy_id:strategy,ticker,version})}`),retry:false,staleTime:30_000});
  if(isPending) return <p role="status">Loading your trade practice...</p>;
  if(isError || !data) return <p role="alert">Trade practice could not load. <button className="btn btn-sm btn-ghost" onClick={()=>void refetch()}>Retry</button></p>;
  const item=data.actual[index % Math.max(1,data.actual.length)];
  return <section className="space-y-3">
    <h3 className="font-semibold">Practice from your trades</h3>
    <p className="text-xs">{data.mode.toUpperCase()} account · {version}. Guided review, not a scored exam or a strategy change.</p>
    {item ? <><ExerciseCard key={item.id} item={item}/><button className="btn btn-sm btn-ghost" onClick={()=>setIndex(index+1)}>Next trade ({index % data.actual.length + 1}/{data.actual.length})</button></> : <p className="text-sm">No complete matching closed trades are available yet. Start with the two teaching examples below.</p>}
    {Object.keys(data.exclusions).length > 0 && <details><summary className="text-xs cursor-pointer">Why some trades are unavailable</summary>{Object.entries(data.exclusions).map(([reason,count])=><p key={reason} className="text-xs">{reason}: {count}</p>)}</details>}
    <details open={!item}><summary className="font-semibold cursor-pointer">Two teaching examples</summary><div className="grid gap-3 mt-3 lg:grid-cols-2">{data.samples.map(sample=><ExerciseCard key={sample.id} item={sample}/>)}</div></details>
    <p className="text-xs" style={{color:'var(--ink-muted)'}}>{data.source}. Samples are fictional and never counted as trade results.</p>
  </section>;
}
