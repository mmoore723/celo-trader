import {useEffect,useRef,useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {CoachCelo} from './learning/CoachCelo';
import {BrokerKeyGuide} from './BrokerKeyGuide';
import './welcome.css';
export function WelcomeGuide({userId,onClose,customer=false,learning=true,onCustomerTab}:{userId:string;onClose:()=>void;customer?:boolean;learning?:boolean;onCustomerTab?:(tab:string)=>void}){
 const navigate=useNavigate();const [index,setIndex]=useState(0);const dialog=useRef<HTMLDivElement>(null);
 const steps=customer?[
 {title:'Welcome to CELO',text:'I’m Coach Celo. Let’s find your way around before doing anything else. Your tier gives you charts and any included lessons. It does not place orders.',target:''},
 {title:'Watch charts',text:'Press Open section to find the chart. Enter a ticker, then press Show chart. Each candle describes how a stock moved during five minutes. Viewing it does not buy anything.',target:'/trading'},
 ...(learning?[{title:'Learning Portal',text:'Start with the Learning path. Read an example, answer the question and get an explanation. Chart workshop reveals candles one at a time so you can practice noticing changes.',target:'/playbooks'}]:[]),
 {title:'No broker keys needed',text:'Your account does not need a brokerage account. Explore at your own pace. Use Take a tour whenever you want to see this guide again.',target:''}
 ]:[
 {title:'Welcome to CELO',text:'I’m Coach Celo. Let’s look around before connecting your broker. This guide only opens pages. It never places orders or changes your settings.',target:''},
 {title:'Daily Brief',text:'Start here to see market context for the day. A promising ticker is an idea to inspect, not a signal that you must buy.',target:'/'},
 {title:'Live Trading',text:'Watch candles and the activity cards together. Open positions show what your account currently holds. Activity explains what the bot is checking or waiting for.',target:'/trading'},
 {title:'Trade Journal',text:'Open a trade to see its saved entry and exit. Bot Decisions explains why a setup progressed or stopped. A preview is not a filled order.',target:'/journal'},
 {title:'Performance',text:'Review results over time. One winning trade does not tell the whole story. Check losses and the number of trades too.',target:'/performance'},
 {title:'Learning Portal',text:'Begin with the Learning path, then practice on charts. Coach Celo explains the examples and your answers. You can learn without connecting keys.',target:'/playbooks'},
 {title:'Settings',text:'This is where you review your broker connection and account settings. Paper means pretend money. Live means real money. Opening Settings does not change either one.',target:'/settings'},
 {title:'Before connecting your broker',text:'Read the key guide below first. You can skip the setup and return to Settings later. Never share your secret key in chat.',target:''}
 ];
 const step=steps[index];
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.focus();return()=>previous?.focus();},[]);
 useEffect(()=>{const target=document.querySelector(`[data-tour="${step.target}"]`);if(target)target.classList.add('celo-tour-highlight');return()=>{target?.classList.remove('celo-tour-highlight');};},[step.target]);
 function finish(){try{localStorage.setItem(`celo_tour_v1_${userId}`,'1');}catch{/* Tour remains usable without browser storage. */}onClose();}
 function open(){if(customer){if(onCustomerTab)onCustomerTab(step.target);else navigate(step.target);}else navigate(step.target);}
 return <div className="welcome-scrim"><div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="welcome-title" className="welcome-guide" onKeyDown={e=>{if(e.key==='Escape'){finish();return;}if(e.key==='Tab'){const items=dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],summary');if(!items?.length)return;const first=items[0],last=items[items.length-1];if(e.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){e.preventDefault();last.focus();}else if(!e.shiftKey&&(document.activeElement===last||document.activeElement===dialog.current)){e.preventDefault();first.focus();}}}}>
 <div className="welcome-heading"><span>GETTING STARTED · {index+1} OF {steps.length}</span><button className="btn btn-ghost" onClick={finish}>Skip tour</button></div>
 <h2 id="welcome-title">{step.title}</h2><CoachCelo><p>{step.text}</p></CoachCelo>
 {step.target&&<button className="btn btn-ghost" onClick={open}>Open {step.title}</button>}
 {!customer&&index===steps.length-1&&<BrokerKeyGuide/>}
 <footer><button className="btn btn-ghost" disabled={index===0} onClick={()=>setIndex(index-1)}>Back</button><button className="btn btn-primary" onClick={()=>index===steps.length-1?finish():setIndex(index+1)}>{index===steps.length-1?'Finish tour':'Next'}</button></footer>
 <p className="welcome-note">Replay with Take a tour. Your progress is remembered on this browser.</p>
 </div></div>
}
