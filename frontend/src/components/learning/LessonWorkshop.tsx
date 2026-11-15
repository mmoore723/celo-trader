import {RetestSkills, RetestComparison, VisualPractice, type TeachingScene} from './VisualPractice';
import {useState} from 'react';
import {CoachCelo} from './CoachCelo';
import {CandlePractice, type PracticeCandle} from './CandlePractice';
type Candle = {open:number;high:number;low:number;close:number};
export type LessonVisualData =
 | {kind:'table';title:string;headers:string[];rows:string[][]}
 | {kind:'line';title:string;labels:string[];values:number[];unit:string;caption:string}
 | {kind:'candles';title:string;bars:Candle[];labels:string[];level:number|null;levelAfter?:number;caption:string;notes:string[]};
export type Workshop = {retestComparison?:boolean;visualPractice?:TeachingScene[];candlePractice?:PracticeCandle[];goal:string;steps:{title:string;explain:string;example:string}[];mistake:string;challenge:{prompt:string;choices:string[];correct:number;explanation:string};application?:{prompt:string;answer:string};visual?:LessonVisualData};
export function LessonWorkshop({workshop,onReview}:{workshop:Workshop;onReview:()=>void}){
 const [step,setStep]=useState(0);const [choice,setChoice]=useState<number|null>(null);const [checked,setChecked]=useState(false);
 const [premium,setPremium]=useState(2);const [quantity,setQuantity]=useState(1);
 const current=workshop.steps[step];const practice=step===workshop.steps.length;
 function move(index:number){setStep(index);setChoice(null);setChecked(false);}
 return <section className="lesson-workshop" aria-label="Guided lesson">
 <p className="workshop-goal"><strong>By the end:</strong> {workshop.goal}</p>
 <nav className="workshop-route" aria-label="Teaching steps">{workshop.steps.map((s,i)=><button key={s.title} className={step===i?'selected':''} aria-current={step===i?'step':undefined} onClick={()=>move(i)}>{i+1}. {s.title}</button>)}<button className={practice?'selected':''} aria-current={practice?'step':undefined} onClick={()=>move(workshop.steps.length)}>Try a new situation</button></nav>
 {!practice&&current?<div className="workshop-columns"><div><p className="portal-eyebrow">STEP {step+1} OF {workshop.steps.length}</p><h3>{current.title}</h3><p>{current.explain}</p><section className="workshop-example"><h4>Walk through it</h4><p>{current.example}</p></section>{workshop.visual&&<LessonVisual visual={workshop.visual}/>}</div><CoachCelo><p><strong>Keep these separate:</strong> {workshop.mistake}</p></CoachCelo></div>:<section><h3>Use the idea in a different situation</h3><p>Practice only. This does not place an order or change your saved lesson score.</p>{workshop.candlePractice?<CandlePractice candles={workshop.candlePractice}/>:workshop.retestComparison&&workshop.visualPractice?<><RetestComparison scenes={workshop.visualPractice}/><RetestSkills/></>:workshop.visualPractice?<VisualPractice scenes={workshop.visualPractice}/>:<><fieldset className="portal-question"><legend>{workshop.challenge.prompt}</legend>{workshop.challenge.choices.map((c,i)=><label key={c}><input type="radio" name="workshop-choice" checked={choice===i} onChange={()=>{setChoice(i);setChecked(false);}}/>{c}</label>)}</fieldset><button className="btn btn-primary" disabled={choice===null} onClick={()=>setChecked(true)}>Explain my answer</button>{checked&&<div className="portal-feedback" role="status"><h4>{choice===workshop.challenge.correct?'Correct. Here is the reasoning.':'Not quite. Let’s work it out.'}</h4><p>{workshop.challenge.explanation}</p></div>}
 </>}
 {workshop.application&&<ApplicationPractice application={workshop.application}/>}
 {!workshop.visual&&<details className="workshop-experiment"><summary>Try the contract-cost calculator</summary><p>Change the quote and contract count. These are practice numbers, not your account or a market quote. Standard 100-share contracts only.</p><label>Option quote per share: ${premium.toFixed(2)}<input aria-label="Practice option premium" type="range" min="0.5" max="5" step="0.25" value={premium} onChange={e=>setPremium(Number(e.target.value))}/></label><label>Contracts: {quantity}<input aria-label="Practice contract count" type="range" min="1" max="5" step="1" value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/></label><output aria-live="polite">${premium.toFixed(2)} × 100 × {quantity} = ${(premium*100*quantity).toFixed(2)} before fees</output><p>Doubling the contract count doubles the purchase cost. This calculator does not estimate a stop loss or recommend a quantity.</p></details>}
 </section>}
 <footer className="workshop-controls"><button className="btn btn-ghost" disabled={step===0} onClick={()=>move(step-1)}>Previous step</button>{practice?<button className="btn btn-primary" onClick={onReview}>Go to the saved knowledge check</button>:<button className="btn btn-primary" onClick={()=>move(step+1)}>{step===workshop.steps.length-1?'Try a new situation':'Next step'}</button>}</footer>
 </section>;
}

function ApplicationPractice({application}:{application:{prompt:string;answer:string}}){
 const [response,setResponse]=useState('');const [revealed,setRevealed]=useState(false);
 return <section className="workshop-application"><h4>Now work it out yourself</h4><label>{application.prompt}<textarea value={response} onChange={e=>setResponse(e.target.value)} placeholder="Write your calculation or reasoning here. This practice note is not saved." rows={3}/></label><button className="btn btn-ghost" aria-expanded={revealed} onClick={()=>setRevealed(!revealed)}>{revealed?'Hide worked answer':'Compare with the worked answer'}</button>{revealed&&<div className="portal-feedback"><strong>Worked answer</strong><p>{application.answer}</p><p>Compare the steps with yours. This is self-check practice, not an automatically graded answer.</p></div>}</section>;
}

// Only revealed bars determine scale and visible data. Later bars never appear early.
export function revealedCandles(visual:Extract<LessonVisualData,{kind:'candles'}>,count:number){
 const bars=visual.bars.slice(0,Math.max(1,Math.min(count,visual.bars.length)));
 return {bars,minimum:Math.min(...(visual.level===null?[]:[visual.level]),...bars.map(b=>b.low)),maximum:Math.max(...(visual.level===null?[]:[visual.level]),...bars.map(b=>b.high))};
}
export function LessonVisual({visual}:{visual:LessonVisualData}){
 const [count,setCount]=useState(1);
 const [point,setPoint]=useState(0);
 if(visual.kind==='table')return <figure className="workshop-visual"><figcaption><strong>{visual.title}</strong><span>Illustrative teaching example</span></figcaption><div className="workshop-table-scroll"><table><thead><tr>{visual.headers.map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{visual.rows.map((r,i)=><tr key={i}>{r.map((c,j)=>j===0?<th scope="row" key={j}>{c}</th>:<td key={j}>{c}</td>)}</tr>)}</tbody></table></div></figure>;
 const candle=visual.kind==='candles';
 const state=candle?revealedCandles(visual,count):null;
 const values=visual.kind==='line'?visual.values:[];
 const minimum=state?state.minimum:Math.min(...values);
 const maximum=state?state.maximum:Math.max(...values);
 const padding=Math.max((maximum-minimum)*.15,candle?.2:1);
 const low=minimum-padding,high=maximum+padding;
 const y=(v:number)=>220-(v-low)/(high-low)*180;
 const number=(v:number)=>v.toLocaleString('en-US',{maximumFractionDigits:2});
 const labels=candle?visual.labels.slice(0,state!.bars.length):visual.labels;
 const x=(i:number)=>75+(labels.length===1?225:i*450/(labels.length-1));
 const current=candle?state!.bars[state!.bars.length-1]:null;
 return <figure className="workshop-visual"><figcaption><strong>{visual.title}</strong><span>Illustrative teaching example{candle?' · Reveal completed candles in order':''}</span></figcaption>
 <svg viewBox="0 0 600 270" role="img" aria-label={visual.title+'. '+(candle?`${count} of ${visual.bars.length} completed candles shown.`:visual.caption)}>
 {[0,.5,1].map(t=>{const v=low+(high-low)*t;return <g key={t}><line x1="60" x2="555" y1={y(v)} y2={y(v)} stroke="currentColor" opacity=".14"/><text x="52" y={y(v)+4} textAnchor="end" className="workshop-axis">{number(v)}</text></g>;})}
 {candle?<>
 {visual.level!==null&&count>=(visual.levelAfter??1)&&<line x1="60" x2="555" y1={y(visual.level)} y2={y(visual.level)} stroke="var(--workshop-reference, #53668c)" strokeDasharray="5 5"/>}
 {state!.bars.map((b,i)=>{const up=b.close>=b.open;return <g key={i} className={up?'workshop-up':'workshop-down'}><line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke="currentColor" strokeWidth="2"/><rect x={x(i)-10} y={Math.min(y(b.open),y(b.close))} width="20" height={Math.max(2,Math.abs(y(b.open)-y(b.close)))} fill="currentColor"/><title>{labels[i]}: open {b.open}, high {b.high}, low {b.low}, close {b.close}</title></g>;})}
 </>:<><polyline points={values.map((v,i)=>`${x(i)},${y(v)}`).join(' ')} fill="none" stroke="#4263d5" strokeWidth="3"/>{values.map((v,i)=><circle key={i} cx={x(i)} cy={y(v)} r={point===i?6:3} fill="#4263d5"/>)}</>}
 {labels.map((l,i)=><text key={i} x={x(i)} y="247" textAnchor="middle" className="workshop-axis">{l}</text>)}
 </svg>
 {candle?<><p className="workshop-chart-key">Green: close at or above open. Red: close below open. {visual.level!==null&&count>=(visual.levelAfter??1)?`Dashed line: $${number(visual.level)} reference.`:''}</p><div className="workshop-chart-controls"><button className="btn btn-ghost" disabled={count===1} onClick={()=>setCount(count-1)}>Previous candle</button><output aria-live="polite">Candle {count} of {visual.bars.length}</output><button className="btn btn-primary" disabled={count===visual.bars.length} onClick={()=>setCount(count+1)}>Next candle</button></div><p className="workshop-observation" aria-live="polite"><strong>{labels[count-1]}:</strong> Open ${number(current!.open)} · High ${number(current!.high)} · Low ${number(current!.low)} · Close ${number(current!.close)}. {visual.notes[count-1]}</p></>:<><label className="workshop-chart-picker">Inspect an example point<select value={point} onChange={e=>setPoint(Number(e.target.value))}>{visual.labels.map((l,i)=><option value={i} key={i}>{l}</option>)}</select></label><output className="workshop-observation" aria-live="polite">{visual.labels[point]}: {number(visual.values[point])} · {visual.unit}</output></>}
 <p>{visual.caption}{!candle&&' Points are example categories, not a uniformly spaced time or price axis.'}</p><details><summary>Read the chart values</summary><div className="workshop-table-scroll"><table><thead><tr>{(candle?['Completed candle','Open','High','Low','Close']:['Example point',visual.unit]).map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{candle?state!.bars.map((b,i)=><tr key={i}><th scope="row">{labels[i]}</th>{[b.open,b.high,b.low,b.close].map((v,j)=><td key={j}>{number(v)}</td>)}</tr>):visual.values.map((v,i)=><tr key={i}><th scope="row">{labels[i]}</th><td>{number(v)}</td></tr>)}</tbody></table></div></details>
 </figure>;
}
