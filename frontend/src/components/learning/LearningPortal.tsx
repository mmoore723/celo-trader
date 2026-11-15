import {VisualPractice} from './VisualPractice';
import { LessonWorkshop, type Workshop } from './LessonWorkshop';
import { CoachCelo } from './CoachCelo';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { Foundations } from './Foundations';
import { OptionLab } from './OptionLab';
import './portal.css';

type Question = {prompt:string;choices:string[]};
type Progress = {passed?:boolean;best_score?:number;attempts?:number};
type Lesson = {id:string;unit:string;title:string;teach:string;example:string;watch:string;questions:Question[];progress:Progress;workshop?:Workshop};
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
 const [selected,setSelected]=useState('lesson-1'); const [view,setView]=useState('catalog');
 const [stage,setStage]=useState(0);
 const [choices,setChoices]=useState<Record<number,number>>({}); const [feedback,setFeedback]=useState<Feedback|null>(null);
 const [saving,setSaving]=useState(false);const [saveError,setSaveError]=useState('');
 function choose(id:string){setView('course');setStage(0);setSelected(id);setChoices({});setFeedback(null);setSaveError('');}
 if(isPending)return <p>Opening your Learning Portal...</p>;
 if(error||!data)return <div role="alert">We could not open your course. <button className="btn" onClick={()=>refetch()}>Try again</button></div>;
 const current=data.lessons.find(l=>l.id===selected); const final=selected==='final'; const item=final?data.final:current;
 const completed=data.lessons.filter(l=>l.progress.passed).length;
 const foundationComplete=data.lessons.slice(0,20).every(l=>l.progress.passed);
 const units=[...new Set(data.lessons.map(l=>l.unit))];
 async function submit(){
  if(!item||saving)return;setSaving(true);setSaveError('');
  try{setFeedback(await read<Feedback>('/api/learning/course/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lesson:item.id,choices:item.questions.map((_,i)=>choices[i])})}));await qc.invalidateQueries({queryKey:key});}
  catch(e){setSaveError((e as Error).message);}finally{setSaving(false);}
 }
 return <section className="learning-portal">
  <header className="portal-welcome"><div><p className="portal-eyebrow">CELO LEARNING PORTAL</p><h1>Learn it. Try it. See why.</h1><p>Build your options skills through short lessons, chart challenges and hands-on experiments.</p></div>
   <div className="portal-progress"><progress aria-label="Lessons completed" value={completed} max={data.lessons.length}/><span>{completed} / {data.lessons.length} lessons completed</span></div>
   <nav className="flex flex-wrap gap-2 mt-4" aria-label="Learning activities">{[['catalog','Explore courses'],['chart','Chart challenges'],['lab','Options lab']].map(([id,label])=><button key={id} className={`btn ${view===id?'btn-primary':'btn-ghost'}`} onClick={()=>setView(id)}>{label}</button>)}</nav>
  </header>
  {view==='catalog'?<><section className="portal-resume"><div><span className="portal-eyebrow">YOUR NEXT STEP</span><h2>{data.lessons.find(l=>!l.progress.passed)?.title??'Keep your skills sharp'}</h2><p>Pick up where you left off, or explore any topic below.</p></div><button className="btn btn-primary" onClick={()=>choose(data.lessons.find(l=>!l.progress.passed)?.id??'lesson-1')}>{completed?'Continue learning':'Start learning'} →</button></section><div className="portal-catalog">{units.map((unit,i)=>{const lessons=data.lessons.filter(l=>l.unit===unit),done=lessons.filter(l=>l.progress.passed).length;return <button key={unit} className="portal-course-card" onClick={()=>choose(lessons.find(l=>!l.progress.passed)?.id??lessons[0].id)}><div className={`course-art art-${i%4}`} aria-hidden="true"><svg viewBox="0 0 240 70"><path d={i%2?'M10 54L45 36L70 44L100 18L130 32L165 12L195 23L230 7':'M10 30L45 46L75 20L105 35L140 14L170 29L200 8L230 19'} fill="none" stroke="currentColor" strokeWidth="3"/><circle cx="140" cy="14" r="5" fill="currentColor"/></svg><span>COURSE {String(i+1).padStart(2,'0')}</span></div><div className="course-card-copy"><h2>{unit}</h2><p>{lessons.map(l=>l.title).slice(0,2).join(' · ')}</p><footer><span>{lessons.length} lessons</span><span>{done?`${done}/${lessons.length} complete`:'Start course →'}</span></footer><progress value={done} max={lessons.length} aria-label={`${unit} progress`}/></div></button>})}</div><section className="portal-resume"><div><h2>Foundation review</h2><p>Ten questions. Explanations after every attempt. Your earlier progress is saved.</p></div><button className="btn btn-ghost" disabled={!foundationComplete} onClick={()=>choose('final')}>{foundationComplete?'Take the review':'Complete the first 20 lessons'}</button></section></>:view==='chart'?<Foundations/>:view==='lab'?<OptionLab/>:<div className="portal-layout">
   <nav className="portal-map" aria-label="Course lessons"><button className="btn btn-ghost mb-3" onClick={()=>setView('catalog')}>← All courses</button><h3>{current?.unit??'Foundation review'}</h3>{data.lessons.filter(l=>l.unit===current?.unit).map((l,i)=><button key={l.id} className={`lesson-link ${selected===l.id?'selected':''}`} aria-current={selected===l.id?'step':undefined} onClick={()=>choose(l.id)}><span>{l.progress.passed?'✓':i+1}</span>{l.title}</button>)}<button className="btn btn-ghost mt-4" onClick={()=>setView('chart')}>Practice on a chart</button><button className="btn btn-ghost mt-2" onClick={()=>setView('lab')}>Try the options lab</button></nav>
   {item&&<article className="portal-lesson" key={item.id}><p className="portal-eyebrow">{final?'PUT IT TOGETHER':current?.unit}</p><h2>{item.title}</h2>
    {!final&&<nav className="lesson-stages" aria-label="Lesson steps">{(current?.workshop?['Guided lesson','Quick recap','Knowledge check']:['Understand','See an example','Try it']).map((name,i)=><button key={name} aria-current={stage===i?'step':undefined} className={stage===i?'active':''} onClick={()=>setStage(i)}><span>{i+1}</span>{name}</button>)}</nav>}
    {current?.workshop&&!final&&stage===0&&<LessonWorkshop key={current.id} workshop={current.workshop} onReview={()=>setStage(2)}/> }
    {current&&!current.workshop&&!final&&stage===0&&<div className="lesson-stage"><p className="portal-teach">{current.teach}</p><CoachCelo><p>{current.watch}</p></CoachCelo><button className="btn btn-primary" onClick={()=>setStage(1)}>Show me an example →</button></div>}
    {current&&!final&&stage===1&&<div className="lesson-stage"><section className="portal-example"><p className="portal-eyebrow">WORKED EXAMPLE</p><p>{current.example}</p></section><p className="portal-prompt">Read the situation, then test your decision on the next step.</p><button className="btn btn-primary" onClick={()=>setStage(2)}>Let me try →</button></div>}
    {final&&<p>This review checks the ideas you practiced. Score at least 80% to complete the foundation course. You can review and retry. Completion is not a trading license or a promise of trading success.</p>}
    {(final||stage===2)&&<form onSubmit={e=>{e.preventDefault();void submit();}}><h3>{final?'Review questions':'Check your understanding'}</h3>{item.questions.map((q,i)=><fieldset key={i} className="portal-question"><legend>{q.prompt}</legend>{q.choices.map((c,j)=><label key={j}><input type="radio" name={`q-${i}`} checked={choices[i]===j} onChange={()=>{setChoices({...choices,[i]:j});setFeedback(null);}} required/>{c}</label>)}</fieldset>)}
     <button className="btn btn-primary" disabled={saving||item.questions.some((_,i)=>choices[i]===undefined)}>{saving?'Saving...':'Check my answer'+(final?'s':'')}</button>
    </form>}
    {saveError&&<p role="alert">{saveError}</p>}
    {(final||stage===2)&&feedback&&<section aria-live="polite" className="portal-feedback"><h3>{feedback.passed?'You’ve got it.':'Let’s look at that again.'} {final?`${feedback.score}%`:''}</h3>{feedback.results.map((r,i)=>{const related=final?data.lessons.find(l=>l.questions.some(q=>q.prompt===item.questions[i].prompt)):current;return <div key={i}><p>{final?`Question ${i+1}: `:''}{r.correct?'Correct. ':'Try again. '}{r.explanation}</p>{!r.correct&&related?.workshop?.visualPractice&&<VisualPractice key={`${selected}:${i}:${feedback.score}`} scenes={related.workshop.visualPractice} startWithWalkthrough/>}</div>;})}{!final&&feedback.passed&&<button className="btn btn-primary mt-3" onClick={()=>choose(data.lessons[data.lessons.findIndex(l=>l.id===selected)+1]?.id??'final')}>Continue</button>}</section>}
   </article>}
  </div>}
  <footer className="portal-sources"><p>{data.disclaimer}</p><p>Continue learning with trusted resources: {data.sources.map(s=><a key={s.url} href={s.url} target="_blank" rel="noreferrer">{s.title}</a>)}</p></footer>
 </section>;
}
