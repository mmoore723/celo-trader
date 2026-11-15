import {useState} from 'react';

export type PracticeCandle = {open:number;high:number;low:number;close:number};
const dollars=(n:number)=>'$'+n.toFixed(2);
export function candleParts(c:PracticeCandle){
 return {body:Math.abs(c.close-c.open),upper:c.high-Math.max(c.open,c.close),lower:Math.min(c.open,c.close)-c.low,range:c.high-c.low};
}
export function candleAnswers(c:PracticeCandle,index:number){
 const p=candleParts(c);
 const answers=[
  {text:`Body ${dollars(p.body)}; whole range ${dollars(p.range)}`,correct:true},
  {text:`Body ${dollars(p.range)}; whole range ${dollars(p.body)}`,correct:false},
  {text:`Body ${dollars(p.upper)}; whole range ${dollars(p.range)}`,correct:false},
 ];
 const offset=index%answers.length;
 return [...answers.slice(offset),...answers.slice(0,offset)];
}
export function candleWalkthrough(c:PracticeCandle){
 const p=candleParts(c),up=c.close>=c.open;
 return [
  {title:'Body: where price started and finished',text:`Follow the blue outline around the thick rectangle. It joins the open at ${dollars(c.open)} to the close at ${dollars(c.close)}. That distance is ${dollars(p.body)}. The thin lines outside it are not part of the body. This candle is ${up?'green because it closed above its open':'red because it closed below its open'}.`},
  {title:'Upper wick: how high price reached',text:`Now follow the purple line above the body. It runs from the top of the body at ${dollars(Math.max(c.open,c.close))} to the high at ${dollars(c.high)}. Price reached that high during the candle, but did not close there. This upper wick measures ${dollars(p.upper)}.`},
  {title:'Lower wick: how low price reached',text:`Follow the orange line below the body. It runs from the bottom of the body at ${dollars(Math.min(c.open,c.close))} to the low at ${dollars(c.low)}. This lower wick measures ${dollars(p.lower)}. A wick shows an extreme price, not the opening or closing price.`},
  {title:'Whole candle: put the pieces together',text:`The full range runs from the low at ${dollars(c.low)} to the high at ${dollars(c.high)}. It includes the lower wick, body and upper wick: ${dollars(p.lower)} + ${dollars(p.body)} + ${dollars(p.upper)} = ${dollars(p.range)}. The candle does not tell us whether the high or low happened first. Try a different candle next and identify the body before measuring the range.`},
 ];
}

// A finished, synthetic candle. Highlighted shapes stay on the same price scale.
export function CandleAnatomy({candle:c,focus=-1}:{candle:PracticeCandle;focus?:number}){
 const range=c.high-c.low;
 const y=(price:number)=>48+(c.high-price)/range*220;
 const top=y(Math.max(c.open,c.close)),bottom=y(Math.min(c.open,c.close));
 const active=(part:number)=>focus===part||focus===3;
 const color=c.close>=c.open?'#15805a':'#bf3954';
 return <figure className="candle-anatomy"><figcaption>Finished practice candle · Made-up prices</figcaption>
 <svg viewBox="0 0 440 320" role="img" aria-label={`Candle: open ${dollars(c.open)}, high ${dollars(c.high)}, low ${dollars(c.low)}, close ${dollars(c.close)}. ${focus<0?'Identify its body and whole range.':candleWalkthrough(c)[focus].title}`}>
 {[{name:'High',price:c.high},{name:'Close',price:c.close},{name:'Open',price:c.open},{name:'Low',price:c.low}].map(p=><g key={p.name}><line x1="188" x2="260" y1={y(p.price)} y2={y(p.price)} stroke="currentColor" opacity=".25" strokeDasharray="3 4"/><text x="270" y={y(p.price)+5} fill="currentColor" fontSize="15">{p.name} {dollars(p.price)}</text></g>)}
 <line x1="166" x2="166" y1={y(c.high)} y2={y(c.low)} stroke={color} strokeWidth="3"/>
 <rect x="143" width="46" y={top} height={bottom-top} fill={color}/>
 {active(0)&&<g data-part="body"><rect x="136" y={top-4} width="60" height={bottom-top+8} rx="5" fill="none" stroke="#3159db" strokeWidth="4"/><line x1="89" x2="133" y1={(top+bottom)/2} y2={(top+bottom)/2} stroke="#3159db" strokeWidth="2"/><text x="18" y={(top+bottom)/2+5} fill="currentColor" fontSize="15">Body</text></g>}
 {active(1)&&<g data-part="upper-wick"><line x1="166" x2="166" y1={y(c.high)} y2={top} stroke="#8855b4" strokeWidth="8"/><line x1="99" x2="161" y1={(y(c.high)+top)/2} y2={(y(c.high)+top)/2} stroke="#8855b4" strokeWidth="2"/><text x="18" y={(y(c.high)+top)/2-6} fill="currentColor" fontSize="15">Upper wick</text></g>}
 {active(2)&&<g data-part="lower-wick"><line x1="166" x2="166" y1={bottom} y2={y(c.low)} stroke="#b56808" strokeWidth="8"/><line x1="99" x2="161" y1={(bottom+y(c.low))/2} y2={(bottom+y(c.low))/2} stroke="#b56808" strokeWidth="2"/><text x="18" y={(bottom+y(c.low))/2+19} fill="currentColor" fontSize="15">Lower wick</text></g>}
 {focus===3&&<path d="M 209 48 H 222 V 268 H 209" fill="none" stroke="currentColor" strokeWidth="2"/>}
 </svg></figure>;
}
export function CandlePractice({candles}:{candles:PracticeCandle[]}){
 const [index,setIndex]=useState(0),[selected,setSelected]=useState<number|null>(null),[checked,setChecked]=useState(false),[focus,setFocus]=useState(0);
 const c=candles[index],answers=candleAnswers(c,index),steps=candleWalkthrough(c);
 function next(){setIndex((index+1)%candles.length);setSelected(null);setChecked(false);setFocus(0);}
 return <section className="candle-practice" aria-label="Candle practice">
 <h3>Read this candle</h3><p>Practice {index+1} of {candles.length}. Use the picture: find where price opened and closed, then find its highest and lowest prices.</p>
 <CandleAnatomy candle={c} focus={checked?focus:-1}/>
 {!checked?<><fieldset className="portal-question"><legend>How big is the body, and how big is the whole range?</legend>{answers.map((a,i)=><label key={a.text}><input type="radio" name="candle-answer" checked={selected===i} onChange={()=>setSelected(i)}/>{a.text}</label>)}</fieldset><button className="btn btn-primary" disabled={selected===null} onClick={()=>{setChecked(true);setFocus(0);}}>Explain my answer</button></>:<>
 <p className="candle-feedback-heading" role="status">{answers[selected!].correct?'Correct. Let’s trace the parts on the candle.':'Not quite. Let’s trace the parts on the candle.'} You chose: {answers[selected!].text}.</p>
 <nav className="workshop-route" aria-label="Candle walkthrough">{['Body','Upper wick','Lower wick','Whole candle'].map((name,i)=><button key={name} className={focus===i?'selected':''} aria-current={focus===i?'step':undefined} onClick={()=>setFocus(i)}>{i+1}. {name}</button>)}</nav>
 <div className="portal-feedback" aria-live="polite"><h4>{steps[focus].title}</h4><p>{steps[focus].text}</p></div>
 <div className="workshop-controls"><button className="btn btn-ghost" disabled={focus===0} onClick={()=>setFocus(focus-1)}>Previous part</button>{focus<3?<button className="btn btn-primary" onClick={()=>setFocus(focus+1)}>Next: {['','upper wick','lower wick','whole candle'][focus+1]}</button>:<button className="btn btn-primary" onClick={next}>Try a different candle</button>}</div>
 </>}
 </section>;
}
