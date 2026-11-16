import {useState} from 'react';
import examples from './historicalRetests.json';
import {CoachCelo} from './CoachCelo';

// Archived educational candles only. No account, configuration or order writes.
export function HistoricalRetests(){
 const [index,setIndex]=useState(0),[revealed,setRevealed]=useState(false),[answer,setAnswer]=useState(''),[step,setStep]=useState(0);
 const e=examples[index],bars=e.bars,last=bars[bars.length-1];
 const outcome=last.close>=e.low&&last.close<=e.high?'stayed undecided':(e.direction==='bullish'?last.close>e.high:last.close<e.low)?'held':'failed';
 const min=Math.min(...bars.map(b=>b.low)),max=Math.max(...bars.map(b=>b.high)),span=Math.max(max-min,.1);
 const y=(v:number)=>265-(v-min+span*.1)/(span*1.2)*220,x=(i:number)=>70+i*480/(bars.length-1);
 const focus=step===0?e.touches.map(n=>n-1):step===1?[e.breakCandle-1]:[bars.length-1];
 const explanation=[`Candles ${e.touches.join(', ')} formed ${e.direction==='bullish'?'resistance':'support'} from $${e.low} to $${e.high}. Follow the highlighted ${e.direction==='bullish'?'highs':'lows'}.`, `Candle ${e.breakCandle} closed at $${bars[e.breakCandle-1].close}, ${e.direction==='bullish'?'above':'below'} the whole zone. This completed close confirmed the ${e.direction==='bullish'?'breakout':'breakdown'} in this exercise.`, `Candle ${bars.length} traded from $${last.low} to $${last.high} and closed at $${last.close}. The retest ${outcome} under our close-based exercise rule. ${outcome==='stayed undecided'?'Its close is inside the zone or exactly on an edge.':e.direction==='bearish'?'We check whether broken support held as resistance.':'We check whether broken resistance held as support.'} Candle color only compares its close with its own open. This does not predict the next candle.`];
 return <section className="visual-practice" aria-label="Historical chart practice">
 <h3>Read a real historical chart</h3><p>Example {index+1} of {examples.length} · {e.ticker} · {e.date} · One-minute candles, Eastern time</p>
 <p>Later candles are excluded. Identify the zone, the break and the retest before revealing Coach Celo’s explanation.</p>
 <div className="visual-practice-layout"><div className="teaching-diagram">
 <svg viewBox="0 0 620 310" role="img" aria-label={`${e.ticker} historical candles numbered 1 through ${bars.length}. Exact prices below. ${revealed?explanation[step]:'No setup annotations.'}`}>
 {[min,(min+max)/2,max].map((v,i)=><g key={i}><line x1="55" x2="570" y1={y(v)} y2={y(v)} stroke="currentColor" opacity=".15"/><text x="50" y={y(v)+4} textAnchor="end" fill="currentColor" fontSize="12">{v.toFixed(2)}</text></g>)}
 {revealed&&<g><rect x="60" y={y(e.high)} width="510" height={Math.max(1,y(e.low)-y(e.high))} fill="#3159db" opacity=".16"/>{[e.low,e.high].map((v,i)=><line key={i} x1="60" x2="570" y1={y(v)} y2={y(v)} stroke="#8153ae" strokeDasharray="4 4"/>)}</g>}
 {bars.map((b,i)=>{const color=b.close>=b.open?'#147c57':'#bc3851',active=revealed&&focus.includes(i);return <g key={i}>
 {active&&<rect x={x(i)-12} y="28" width="24" height="240" fill="#3159db" opacity=".12"/>}
 <line x1={x(i)} x2={x(i)} y1={y(b.high)} y2={y(b.low)} stroke={color} strokeWidth="2"/><rect x={x(i)-7} y={y(Math.max(b.open,b.close))} width="14" height={Math.max(1,Math.abs(y(b.open)-y(b.close)))} fill={color}/>
 {active&&<circle data-coach-focus="true" data-coach-key={`${e.id}:${step}:${i}`} cx={x(i)} cy={y(step===0?(e.direction==='bullish'?b.high:b.low):b.close)} r="4" fill="#3159db"/>}
 <text x={x(i)} y="289" textAnchor="middle" fill="currentColor" fontSize="12">{i+1}</text></g>})}</svg>
 <details><summary>Exact recorded prices</summary><div className="workshop-table-scroll"><table><thead><tr>{['Candle','Time ET','Open','High','Low','Close'].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{bars.map((b,i)=><tr key={i}><th>{i+1}</th><td>{b.time}</td>{[b.open,b.high,b.low,b.close].map((v,k)=><td key={k}>${v}</td>)}</tr>)}</tbody></table></div></details>
 <p>Saved Tradier history, recovered later. This is a historical chart exercise, not a replay of when the bot received prices.</p>
 </div><div>{!revealed?<><label>Your reading of the chart<textarea rows={4} value={answer} onChange={event=>setAnswer(event.target.value)} placeholder="Zone and forming candles; break candle; retest close and result."/></label><p>Your answer stays here only. Compare your reasoning with Coach Celo; this is not automatically graded.</p><button className="btn btn-primary" disabled={!answer.trim()} onClick={()=>setRevealed(true)}>Show me why</button></>:<><nav className="workshop-route" aria-label="Historical explanation">{['Zone formation','Completed break','Retest close'].map((t,i)=><button key={t} className={step===i?'selected':''} onClick={()=>setStep(i)}>{t}</button>)}</nav><CoachCelo><p aria-live="polite">{explanation[step]}</p></CoachCelo><p>Your answer: {answer}</p></>}
 <button className="btn btn-ghost" onClick={()=>{setIndex((index+1)%examples.length);setAnswer('');setRevealed(false);setStep(0);}}>Try another historical chart</button></div></div></section>;
}
