import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';

type Lesson = {id:string; title:string; intro:string; candles:number[][]; notes:string[]; question:string; choices:string[]; progress:{passed:boolean;attempts:number}};
async function read<T>(url:string, options?:RequestInit):Promise<T> {
  const response = await fetch(url, {credentials:'include', ...options});
  if (!response.ok) throw new Error('Your lesson could not be saved or loaded. Please try again.');
  return response.json();
}
export function Foundations() {
  const {user} = useAuth();
  const qc = useQueryClient();
  const key = ['chart-foundations', user?.user_id];
  const {data, isPending, error, refetch} = useQuery({queryKey:key, queryFn:()=>read<{source:string;lessons:Lesson[]}>('/api/learning/foundations')});
  const [selected,setSelected] = useState('candle');
  const [step,setStep] = useState(0);
  const [feedback,setFeedback] = useState<{correct:boolean;explanation:string}|null>(null);
  const [saving,setSaving] = useState(false);
  const [saveError,setSaveError] = useState('');
  const lesson = data?.lessons.find(l=>l.id===selected);
  async function answer(choice:number) {
    if (!lesson || saving) return;
    setSaving(true); setSaveError('');
    try {
      setFeedback(await read('/api/learning/foundations/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lesson:lesson.id,choice})}));
      await qc.invalidateQueries({queryKey:key});
    } catch(e) {setSaveError((e as Error).message);} finally {setSaving(false);}
  }
  if(isPending) return <p>Opening chart basics...</p>;
  if(error || !lesson) return <div role="alert">Could not load chart basics. <button className="btn" onClick={()=>refetch()}>Try again</button></div>;
  // Fixed teaching scale. Future candles are absent from the SVG, not just hidden.
  const y=(price:number)=>270-(price-98)*26;
  return <section className="card p-5">
    <h2 className="text-xl font-semibold">Chart basics</h2>
    <p className="text-sm mt-2" style={{color:'var(--ink-muted)'}}>Learn one candle at a time, then check your understanding. These are invented teaching examples, not real trades or buy instructions.</p>
    <nav aria-label="Chart lessons" className="flex flex-wrap gap-2 my-4">{data?.lessons.map(l=><button key={l.id} className={`btn ${selected===l.id?'btn-primary':'btn-ghost'}`} onClick={()=>{setSelected(l.id);setStep(0);setFeedback(null);setSaveError('');}}>{l.title}{l.progress.passed?' ✓':''}</button>)}</nav>
    <p className="mb-4">{lesson.intro}</p>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(250px,1fr)]">
      <div>
        <svg viewBox="0 0 520 330" role="img" aria-label={`${lesson.title}. ${step+1} completed example candles revealed.`} style={{width:'100%',background:'var(--surface)',border:'1px solid var(--border)',borderRadius:12}}>
          {[99,101,103,105].map(p=><g key={p}><line x1="35" x2="465" y1={y(p)} y2={y(p)} stroke="var(--border)"/><text x="470" y={y(p)+4} fill="var(--ink-muted)" fontSize="12">${p}</text></g>)}
          {selected==='level' && <g><line x1="35" x2="465" y1={y(102)} y2={y(102)} stroke="#3159db" strokeDasharray="6 5"/><text x="40" y={y(102)-10} fill="#3159db" fontSize="13">Example level $102</text></g>}
          {lesson.candles.slice(0,step+1).map(([o,h,l,c],i)=>{const x=90+i*100;const color=c>=o?'#12805c':'#bd3d54';return <g key={i}><line x1={x} x2={x} y1={y(h)} y2={y(l)} stroke={color} strokeWidth="2"/><rect x={x-15} y={y(Math.max(o,c))} width="30" height={Math.max(2,Math.abs(y(o)-y(c)))} fill={color}/><text x={x} y="310" textAnchor="middle" fill="var(--ink-muted)" fontSize="12">Candle {i+1}</text></g>;})}
        </svg>
        <div className="flex gap-2 mt-3"><button className="btn btn-ghost" disabled={step===0} onClick={()=>setStep(s=>s-1)}>Back</button><button className="btn btn-primary" disabled={step===lesson.candles.length-1} onClick={()=>setStep(s=>s+1)}>Next candle</button><span className="self-center text-sm">{step+1} of {lesson.candles.length}</span></div>
      </div>
      <aside className="rounded-xl p-4" style={{background:'color-mix(in srgb, var(--accent) 7%, var(--surface))'}}>
        <h3 className="font-semibold">Coach Celo</h3>
        <p className="mt-3 leading-relaxed" aria-live="polite">{lesson.notes[step]}</p>
        <p className="text-sm mt-4" style={{color:'var(--ink-muted)'}}>Open: ${lesson.candles[step][0]} · High: ${lesson.candles[step][1]} · Low: ${lesson.candles[step][2]} · Close: ${lesson.candles[step][3]}</p>
        {step===lesson.candles.length-1 && <div className="mt-5"><h4 className="font-semibold">Your turn</h4><p className="my-2">{lesson.question}</p><div className="flex flex-col gap-2">{lesson.choices.map((choice,i)=><button key={choice} className="btn btn-ghost" style={{textAlign:'left',whiteSpace:'normal'}} disabled={saving} onClick={()=>answer(i)}>{choice}</button>)}</div>{feedback && <p role="status" className="mt-3"><strong>{feedback.correct?'That’s right.':'Try again. '}</strong> {feedback.explanation}</p>}{saveError && <p role="alert">{saveError}</p>}<p className="text-sm mt-3">{lesson.progress.passed?'Understanding checked.':'Complete the question to save your progress.'}</p></div>}
      </aside>
    </div>
  </section>;
}
