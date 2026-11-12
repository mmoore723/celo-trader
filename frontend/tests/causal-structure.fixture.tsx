import {createRoot} from 'react-dom/client';
import {useState} from 'react';
import {TradeChart} from '../src/components/charts/TradeChart';
import '../src/index.css';
const bars=Array.from({length:140},(_,i)=>{
  const close=390+Math.sin(i/3)*2+Math.sin(i/19)*4;
  return {time:new Date(Date.UTC(2026,10,11,14,30+i)).toISOString(),open:close-.1,high:close+.5,low:close-.5,close,volume:1000};
});
function Fixture(){
  const [count,setCount]=useState(140);
  return <main style={{maxWidth:1000,margin:'20px auto'}}>
    <h1>Chart-only fixture. Synthetic prices, no trading.</h1>
    <button onClick={()=>setCount(90)}>Earlier replay</button>
    <button onClick={()=>setCount(140)}>Full replay</button>
    <TradeChart bars={bars} revealCount={count} showVwap={false} showOR={false} showExecutionGrade={false} height={460}/>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
