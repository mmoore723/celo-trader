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
