import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { Foundations } from './Foundations';
import './portal.css';

type Question = {prompt:string;choices:string[]};
type Progress = {passed?:boolean;best_score?:number;attempts?:number};
type Lesson = {id:string;unit:string;title:string;teach:string;example:string;watch:string;questions:Question[];progress:Progress};
type Course = {version:string;lessons:Lesson[];sources:{title:string;url:string}[];final:{id:string;title:string;questions:Question[];progress:Progress;pass_percent:number};disclaimer:string};
type Feedback = {passed:boolean;score:number;results:{correct:boolean;explanation:string}[]};
async function read<T>(url:string,options?:RequestInit):Promise<T> {
 const r=await fetch(url,{credentials:'include',...options});
 if(!r.ok) throw new Error('Your lesson could not be loaded or saved. Please try again.');
 return r.json();
}
export function LearningPortal(){
 const {user}=useAuth(); const qc=useQueryClient(); const key=['learning-course',user?.user_id];
 const {data,error,isPending,refetch}=useQuery({queryKey:key,queryFn:()=>read<Course>('/api/learning/course')});
 const [selected,setSelected]=useState('lesson-1'); const [view,setView]=useState('course');
 const [choices,setChoices]=useState<Record<number,number>>({}); const [feedback,setFeedback]=useState<Feedback|null>(null);
 const [saving,setSaving]=useState(false);const [saveError,setSaveError]=useState('');
 function choose(id:string){setSelected(id);setChoices({});setFeedback(null);setSaveError('');}
 if(isPending)return <p>Opening your Learning Portal...</p>;
 if(error||!data)return <div role="alert">We could not open your course. <button className="btn" onClick={()=>refetch()}>Try again</button></div>;
 const current=data.lessons.find(l=>l.id===selected); const final=selected==='final'; const item=final?data.final:current;
 const completed=data.lessons.filter(l=>l.progress.passed).length;
 const units=[...new Set(data.lessons.map(l=>l.unit))];
 async function submit(){
  if(!item||saving)return;setSaving(true);setSaveError('');
  try{setFeedback(await read<Feedback>('/api/learning/course/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lesson:item.id,choices:item.questions.map((_,i)=>choices[i])})}));await qc.invalidateQueries({queryKey:key});}
  catch(e){setSaveError((e as Error).message);}finally{setSaving(false);}
 }
 return <section className="learning-portal">
  <header className="portal-welcome"><p className="portal-eyebrow">LEARNING PORTAL</p><h1>Understand the trade, one step at a time.</h1><p>Start with what an option is. Learn to read the chart, understand the contract and write a paper-trade plan.</p>
   <div className="portal-progress"><progress aria-label="Lessons completed" value={completed} max={data.lessons.length}/><span>{completed} of {data.lessons.length} lessons completed</span></div>
   <nav className="flex flex-wrap gap-2 mt-4" aria-label="Learning activities"><button className={`btn ${view==='course'?'btn-primary':'btn-ghost'}`} onClick={()=>setView('course')}>Learning path</button><button className={`btn ${view==='chart'?'btn-primary':'btn-ghost'}`} onClick={()=>setView('chart')}>Chart workshop</button></nav>
  </header>
  <details className="portal-family"><summary>Learning together? A guide for parents and beginners</summary><p>Use a parent or guardian’s account. Work through one lesson together, explain the example in your own words, then answer the check. Spend as long as you need. Use pretend money only. No child profile or brokerage account is needed.</p><p>Ask: What happened? What could go wrong? What information is still missing? An incorrect answer is a reason to practice, not a reason to rush.</p></details>
  {view==='chart'?<Foundations/>:<div className="portal-layout">
   <nav className="portal-map" aria-label="Course lessons">{units.map((unit,i)=><details key={unit} open={current?.unit===unit}><summary>{i+1}. {unit}</summary>{data.lessons.filter(l=>l.unit===unit).map(l=><button key={l.id} className={selected===l.id?'selected':''} aria-current={selected===l.id?'step':undefined} onClick={()=>choose(l.id)}>{l.progress.passed?'✓ ':''}{l.title}</button>)}</details>)}<button className="btn mt-3" disabled={completed!==data.lessons.length} onClick={()=>choose('final')}>Final knowledge check{data.final.progress.passed?' ✓':''}</button>{completed!==data.lessons.length&&<p className="text-sm mt-2">Finish the lesson checks to unlock the final check.</p>}</nav>
   {item&&<article className="portal-lesson" key={item.id}><p className="portal-eyebrow">{final?'PUT IT TOGETHER':current?.unit}</p><h2>{item.title}</h2>
    {current&&!final&&<><p className="portal-teach">{current.teach}</p><section className="portal-example"><h3>Let’s work through it</h3><p>{current.example}</p></section><aside className="portal-remember"><h3>Remember this</h3><p>{current.watch}</p></aside><p className="portal-prompt">Your turn: explain this example out loud, then change one number or condition. What changes, and what stays the same?</p></>}
    {final&&<p>This review checks the ideas you practiced. Score at least 80% to complete the foundation course. You can review and retry. Completion is not a trading license or a promise of trading success.</p>}
    <form onSubmit={e=>{e.preventDefault();void submit();}}><h3>{final?'Review questions':'Check your understanding'}</h3>{item.questions.map((q,i)=><fieldset key={i} className="portal-question"><legend>{q.prompt}</legend>{q.choices.map((c,j)=><label key={j}><input type="radio" name={`q-${i}`} checked={choices[i]===j} onChange={()=>{setChoices({...choices,[i]:j});setFeedback(null);}} required/>{c}</label>)}</fieldset>)}
     <button className="btn btn-primary" disabled={saving||item.questions.some((_,i)=>choices[i]===undefined)}>{saving?'Saving...':'Check my answer'+(final?'s':'')}</button>
    </form>
    {saveError&&<p role="alert">{saveError}</p>}
    {feedback&&<section aria-live="polite" className="portal-feedback"><h3>{feedback.passed?'You’ve got it.':'Let’s look at that again.'} {final?`${feedback.score}%`:''}</h3>{feedback.results.map((r,i)=><p key={i}>{final?`Question ${i+1}: `:''}{r.correct?'Correct. ':'Try again. '}{r.explanation}</p>)}{!final&&feedback.passed&&<button className="btn btn-primary mt-3" onClick={()=>choose(data.lessons[data.lessons.findIndex(l=>l.id===selected)+1]?.id??'final')}>Continue</button>}</section>}
   </article>}
  </div>}
  <footer className="portal-sources"><p>{data.disclaimer}</p><p>Continue learning with trusted resources: {data.sources.map(s=><a key={s.url} href={s.url} target="_blank" rel="noreferrer">{s.title}</a>)}</p></footer>
 </section>;
}
