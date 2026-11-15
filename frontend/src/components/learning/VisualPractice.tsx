import {useId, useState} from 'react';
import {CoachCelo} from './CoachCelo';

export type TeachingScene = {
 title:string; prompt:string; choices:string[]; correct:number;
 visual:{kind:'bars'|'path'|'candles'|'flow';labels:string[];values?:number[];bars?:{open:number;high:number;low:number;close:number}[];reference?:number;referenceAt?:number;unit:string};
 buildup?:{count:number;text:string}[];
 steps:{title:string;text:string;focus:number[]}[];
};
export function practiceChoices(scene:TeachingScene,index:number){
 const answers=scene.choices.map((text,i)=>({text,correct:i===scene.correct}));
 const offset=index%answers.length;return [...answers.slice(offset),...answers.slice(0,offset)];
}
export function TeachingDiagram({scene,step=-1,revealCount}:{scene:TeachingScene;step?:number;revealCount?:number}){
 const v=scene.visual,focus=step<0?[]:scene.steps[step].focus;
 const count=revealCount??v.labels.length,labels=v.labels.slice(0,count);
 const nums=v.bars?v.bars.flatMap(b=>[b.high,b.low]):v.values??[0,1];
 const low=Math.min(...nums,...(v.kind==='bars'?[0]:[]),...(v.reference===undefined?[]:[v.reference]));
 const high=Math.max(...nums,...(v.kind==='bars'?[0]:[]),...(v.reference===undefined?[]:[v.reference]));
 const pad=Math.max((high-low)*.12,.1),y=(n:number)=>230-(n-low+pad)/(high-low+2*pad)*185;
 const x=(i:number)=>75+i*450/Math.max(1,v.labels.length-1);
 const fmt=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:3});
 return <figure className="teaching-diagram"><figcaption><strong>{scene.title}</strong><span>Made-up teaching example · {v.unit}</span></figcaption>
 {v.kind==='flow'?<ol className="teaching-flow">{labels.map((label,i)=><li key={i} data-highlighted={focus.includes(i)}><b>{i+1}</b><span>{label}</span>{focus.includes(i)&&<strong className="teaching-look">Look here</strong>}</li>)}</ol>:<>
 <svg viewBox="0 0 600 290" role="img" aria-label={`${scene.title}. ${step<0?'Inspect the example.':scene.steps[step].title+'. '+scene.steps[step].text}`}>
 {[low,(low+high)/2,high].map((n,i)=><g key={i}><line x1="55" x2="555" y1={y(n)} y2={y(n)} stroke="currentColor" opacity=".15"/><text x="50" y={y(n)+4} textAnchor="end" fill="currentColor" fontSize="12">{fmt(n)}</text></g>)}
 {v.reference!==undefined&&count>=(v.referenceAt??0)&&<g><line x1="55" x2="555" y1={y(v.reference)} y2={y(v.reference)} stroke="#8153ae" strokeWidth="2" strokeDasharray="6 4"/><text x="550" y={y(v.reference)-8} textAnchor="end" fill="currentColor" fontSize="12">Reference {fmt(v.reference)}</text></g>}
 {v.kind==='path'&&<polyline points={v.values!.slice(0,count).map((n,i)=>`${x(i)},${y(n)}`).join(' ')} fill="none" stroke="#3159db" strokeWidth="3"/>}
 {labels.map((label,i)=>{const active=focus.includes(i),b=v.bars?.[i],n=v.values?.[i]??b?.close??0;return <g key={i} data-highlighted={active}>
 {active&&<rect x={x(i)-25} y="26" width="50" height="215" rx="8" fill="#3159db" fillOpacity=".12" stroke="#3159db" strokeWidth="2" strokeDasharray="4 3"/>}
 {b?<><line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={b.close>=b.open?'#147c57':'#bc3851'} strokeWidth="3"/><rect x={x(i)-10} y={Math.min(y(b.open),y(b.close))} width="20" height={Math.max(2,Math.abs(y(b.open)-y(b.close)))} fill={b.close>=b.open?'#147c57':'#bc3851'}/></>:v.kind==='bars'?<rect x={x(i)-16} y={Math.min(y(0),y(n))} width="32" height={Math.max(2,Math.abs(y(n)-y(0)))} fill={n>=0?'#3159db':'#bc3851'}/>:<circle cx={x(i)} cy={y(n)} r={active?7:4} fill="#3159db"/>}
 <text x={x(i)} y="258" textAnchor="middle" fill="currentColor" fontSize="12">{label}</text>
 <text x={x(i)} y="277" textAnchor="middle" fill="currentColor" fontSize="12">{fmt(n)}</text>
 </g>;})}
 </svg><p className="teaching-legend">{step<0?'Read the labels before choosing.':'Blue dashed outlines show where to look in this step.'} {v.kind==='path'?'Points are labeled observations, not equally spaced times.':v.kind==='candles'?'Each bar is a completed candle. Numbers below are closing prices.':'Bars share the same scale and start at zero.'}</p>
 <details><summary>Read the picture values</summary><div className="workshop-table-scroll"><table><thead><tr><th>Observation</th>{(v.bars?['Open','High','Low','Close']:[v.unit]).map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{labels.map((l,i)=><tr key={i}><th scope="row">{l}</th>{(v.bars?[v.bars[i].open,v.bars[i].high,v.bars[i].low,v.bars[i].close]:[v.values![i]]).map((n,j)=><td key={j}>{fmt(n)}</td>)}</tr>)}</tbody></table></div></details>
 </>}
 </figure>;
}
// Local, ungraded teaching only. No account, order, settings or progress writes.
export function VisualPractice({scenes,startWithWalkthrough=false}:{scenes:TeachingScene[];startWithWalkthrough?:boolean}){
 const id=useId();const [index,setIndex]=useState(0),[answer,setAnswer]=useState<number|null>(null),[checked,setChecked]=useState(startWithWalkthrough),[step,setStep]=useState(0);
 const [reveal,setReveal]=useState(0);
 const scene=scenes[index],intro=scene.buildup,building=!checked&&!!intro&&reveal<intro.length,choices=practiceChoices(scene,index),current=scene.steps[step];
 function next(){setIndex((index+1)%scenes.length);setAnswer(null);setChecked(false);setStep(0);setReveal(0);}
 return <section className="visual-practice" aria-label="Visual skill practice">
 <p className="portal-eyebrow">EXAMPLE {index+1} OF {scenes.length} · PRACTICE ONLY</p>
 {startWithWalkthrough&&answer===null&&checked&&<p>Let’s see the same idea in a worked example. These practice numbers may differ from your saved question.</p>}
 <div className="visual-practice-layout"><TeachingDiagram scene={scene} step={checked?step:-1} revealCount={building?intro![reveal].count:undefined}/><div>
 {building?<><CoachCelo><h4>Build the setup first</h4><p>{intro![reveal].text}</p></CoachCelo><div className="workshop-controls"><button type="button" className="btn btn-ghost" disabled={reveal===0} onClick={()=>setReveal(reveal-1)}>Previous candles</button><button type="button" className="btn btn-primary" onClick={()=>setReveal(reveal+1)}>{reveal<intro!.length-1?"Reveal next candles":"Answer the question"}</button></div></>:!checked?<><fieldset className="portal-question"><legend>{scene.prompt}</legend>{choices.map((a,i)=><label key={a.text}><input type="radio" name={id} checked={answer===i} onChange={()=>setAnswer(i)}/>{a.text}</label>)}</fieldset><button type="button" className="btn btn-primary" disabled={answer===null} onClick={()=>{setChecked(true);setStep(0);setReveal(0);}}>Show me why</button></>:<>
 <p role="status">{answer===null?'Follow the highlighted parts.':`${choices[answer].correct?'Correct.':'Not quite.'} You chose: ${choices[answer].text}`}</p>
 <nav className="workshop-route" aria-label="Visual explanation steps">{scene.steps.map((s,i)=><button type="button" key={s.title} className={step===i?'selected':''} aria-current={step===i?'step':undefined} onClick={()=>setStep(i)}>{i+1}. {s.title}</button>)}</nav>
 <CoachCelo><div aria-live="polite"><h4>{current.title}</h4><p>{current.text}</p></div></CoachCelo>
 <div className="workshop-controls"><button type="button" className="btn btn-ghost" disabled={step===0} onClick={()=>setStep(step-1)}>Previous highlight</button>{step<scene.steps.length-1?<button type="button" className="btn btn-primary" onClick={()=>setStep(step+1)}>Next highlight</button>:<button type="button" className="btn btn-primary" onClick={next}>Try a different example</button>}</div>
 </>}
 </div></div></section>;
}

export function retestPassed(scene:TeachingScene){
 const bars=scene.visual.bars;
 return !!bars?.length&&scene.visual.reference!==undefined&&bars[bars.length-1].close>scene.visual.reference;
}
export function freshRetestPair(round:number):TeachingScene[]{
 return [0,1].map(i=>{
  const level=round%2===0?(i===0?120:35):(i===0?60:95);
  const held=(round+i)%2===0;
  const offsets=[[-2,0,-2.4,-.6],[-.6,-.3,-2.1,-1.8],[-1.8,-.05,-2,-.4],[-.4,-.2,-1.7,-1.4],[-1.4,-.1,-1.5,-.3],[-.3,.9,-.4,.6],held?[.5,.65,-.1,.2]:[-.5,.2,-.7,-.3]];
  return {title:`Chart ${i===0?'A':'B'}: $${level} level`,prompt:'Did the retest hold above the old resistance?',choices:['Passed','Failed'],correct:held?0:1,visual:{kind:'candles',labels:['Touch 1','Pullback','Touch 2','Pullback','Before','Break','Retest'],bars:offsets.map(([open,high,low,close])=>({open:level+open,high:level+high,low:level+low,close:level+close})),reference:level,referenceAt:4,unit:'stock price in dollars'},steps:[{title:'Where the level came from',text:'Two earlier approaches reached this area and pulled back.',focus:[0,2]},{title:'The breakout',text:'The breakout candle closed above the earlier resistance.',focus:[5]},{title:'Check the retest close',text:`The retest closed $${(level+(held?.2:-.3)).toFixed(2)}, ${held?'above':'below'} $${level.toFixed(2)}.`,focus:[6]}]};
 });
}
export function RetestComparison({scenes}:{scenes:TeachingScene[]}){
 const id=useId();const [round,setRound]=useState(-1);const [stage,setStage]=useState(2);
 const [answers,setAnswers]=useState<(boolean|null)[]>([null,null]);const [checked,setChecked]=useState(false);
 const worked=round<0,pair=worked?scenes.slice(0,2):freshRetestPair(round);
 function next(){setRound(round+1);setAnswers([null,null]);setChecked(false);setStage(2);}
 return <section className="retest-comparison" aria-label="Compare two retests">
 <h3>{worked?'Same idea, two different retests':'Your turn: judge both retests'}</h3>
 <p>For this exercise, a retest passes when its completed candle closes above the old resistance. A close below it fails. Passing does not guarantee the next price move.</p>
 {worked&&<div className="workshop-controls" aria-label="Reveal the setup">{['How resistance formed','The breakout','The retest'].map((label,i)=><button key={label} className="btn btn-ghost" aria-pressed={stage===i} onClick={()=>setStage(i)}>{label}</button>)}</div>}
 <div className="retest-pair">{pair.map((scene,i)=>{const passed=retestPassed(scene),level=scene.visual.reference!,close=scene.visual.bars!.at(-1)!.close;return <article key={`${round}-${i}`}>
 <TeachingDiagram scene={scene} step={worked?stage:checked?2:-1} revealCount={worked?[4,6,7][stage]:7}/>
 {!worked&&<fieldset disabled={checked}><legend>Chart {i===0?'A':'B'}: did the retest pass or fail?</legend>{[true,false].map(value=><label key={String(value)}><input type="radio" name={`${id}-${i}`} checked={answers[i]===value} onChange={()=>setAnswers(answers.map((a,n)=>n===i?value:a))}/>{value?'Passed: closed above the level':'Failed: closed below the level'}</label>)}</fieldset>}
 {(worked||checked)&&<CoachCelo><p><strong>{worked?(stage===2?(passed?'Retest passed.':'Retest failed.'):'Follow the highlighted candles.'):(answers[i]===passed?'You got this one right.':'Let’s look again.')}</strong> {worked&&stage<2?scene.steps[stage].text:`Follow the blue outline to the retest candle. Its close is $${close.toFixed(2)}. Compare that with the $${level.toFixed(2)} line: the close is ${passed?'above it, so the old resistance held as support in this example':'below it, so the breakout did not hold on this retest'}. The wick can cross the line; this exercise judges the close, not the candle’s color.`}</p></CoachCelo>}
 </article>})}</div>
 {!worked&&!checked&&<button className="btn btn-primary" disabled={answers.some(a=>a===null)} onClick={()=>setChecked(true)}>Have Coach Celo explain my answers</button>}
 {(worked||checked)&&<button className="btn btn-primary" onClick={next}>{worked?'Try a different pair':'Try another pair'}</button>}
 </section>;
}
