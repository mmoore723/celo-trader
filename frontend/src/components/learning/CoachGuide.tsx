import {useEffect,useRef,useState} from 'react';
import {CoachRig} from './CoachRig';
import type {CoachMotion} from './coachMotion';
import './coach.css';

type Spot={x:number;y:number;tx:number;ty:number;width:number;height:number;visible:boolean;chart:boolean;key:string};
const empty:Spot={x:0,y:0,tx:0,ty:0,width:0,height:0,visible:false,chart:false,key:''};
const scopeSelector='.teaching-diagram,.workshop-visual,.candle-practice,.visual-practice,.option-lab,.portal-lesson,.portal-resume';
// Presentation only: follows rendered teaching targets. Never advances lessons or changes focus.
export function CoachGuide({children}:{children:React.ReactNode}){
 const root=useRef<HTMLDivElement>(null),previous=useRef<Spot>(empty);
 const [spot,setSpot]=useState(empty),[paused,setPaused]=useState(false),[hidden,setHidden]=useState(false);
 const [reduced,setReduced]=useState(false),[phase,setPhase]=useState<CoachMotion>('idle');
 useEffect(()=>{const q=window.matchMedia('(prefers-reduced-motion: reduce)');const sync=()=>setReduced(q.matches);sync();q.addEventListener('change',sync);return()=>q.removeEventListener('change',sync);},[]);
 useEffect(()=>{
  const el=root.current;if(!el)return;let raf=0,active:Element|null=null;
  const visible=(node:Element)=>{const b=node.getBoundingClientRect();return b.width>0&&b.height>0&&b.bottom>90&&b.top<window.innerHeight-60&&!node.closest('[hidden]');};
  const update=()=>{
   raf=0;if(hidden||document.hidden){setSpot(s=>s.visible?{...s,visible:false}:s);return;}
   if(active&&!el.contains(active))active=null;
   const inScope=active??el;
   const targets=[...inScope.querySelectorAll('[data-coach-focus="true"]')].filter(visible);
   let target=targets[0];
   if(!target)target=[...inScope.querySelectorAll('.workshop-observation,.workshop-route .selected,.workshop-controls .btn-primary:not(:disabled),.portal-resume .btn,.portal-teach,.portal-example,h3,h2')].find(visible)!;
   if(!target&&active){active=null;target=[...el.querySelectorAll('[data-coach-focus="true"],.portal-resume .btn,.portal-lesson h2')].find(visible)!;}
   if(!target){setSpot(s=>s.visible?{...s,visible:false}:s);return;}
   const r=el.getBoundingClientRect(),t=target.getBoundingClientRect(),size=window.innerWidth<620?68:104;
   const local=target.closest('.lesson-workshop')?.querySelector('.coach-local-anchor');
   const anchor=local?.getBoundingClientRect();
   const x=anchor?anchor.left:r.right-size-2,y=anchor?anchor.top:Math.max(88,Math.min(window.innerHeight-size*1.6-58,t.top+t.height/2-size*.35));
   const next={x,y,tx:t.left+t.width/2,ty:t.top+t.height/2,width:t.width,height:t.height,visible:r.right>size&&r.left<window.innerWidth&&r.bottom>88,chart:!!target.closest('svg'),key:target.getAttribute('data-coach-key')??target.getAttribute('aria-label')??target.textContent?.slice(0,80)??'chart'};
   setSpot(old=>Object.keys(next).every(k=>next[k as keyof Spot]===old[k as keyof Spot])?old:next);
  };
  const schedule=()=>{if(!raf)raf=requestAnimationFrame(update);};
  const follow=(event:Event)=>{const node=event.target as Element;if(node.closest('[data-guide-ui]'))return;active=node.closest(scopeSelector);schedule();};
  const observer=new MutationObserver(schedule);observer.observe(el,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['data-coach-focus','data-coach-key','aria-current','class']});
  const resize=new ResizeObserver(schedule);resize.observe(el);
  el.addEventListener('click',follow);el.addEventListener('focusin',follow);window.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);document.addEventListener('visibilitychange',schedule);schedule();
  return()=>{cancelAnimationFrame(raf);observer.disconnect();resize.disconnect();el.removeEventListener('click',follow);el.removeEventListener('focusin',follow);window.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule);document.removeEventListener('visibilitychange',schedule);};
 },[hidden]);
 useEffect(()=>{
  const old=previous.current;previous.current=spot;
  if(!spot.visible){setPhase('idle');return;}
  if(paused||reduced){setPhase('pointing');return;}
  const moved=old.visible&&(old.key!==spot.key||Math.abs(old.y-spot.y)>55);
  setPhase(moved?'walking':'turning');
  const turn=setTimeout(()=>setPhase('turning'),moved?750:0);
  const rest=setTimeout(()=>setPhase('idle'),7000);
  const point=setTimeout(()=>setPhase('pointing'),moved?1000:250);
  return()=>{clearTimeout(turn);clearTimeout(point);clearTimeout(rest);};
 },[spot.key,spot.visible,paused,reduced]);
 const size=typeof window!=='undefined'&&window.innerWidth<620?68:104;
 return <div ref={root} className="coach-guided" data-motion={paused||reduced?'off':'on'}>
  <div className="coach-guide-tools" data-guide-ui><span>Coach Celo follows your lesson</span><button type="button" onClick={()=>setPaused(!paused)} aria-pressed={paused}>{paused?'Resume movement':'Pause movement'}</button><button type="button" onClick={()=>setHidden(!hidden)} aria-pressed={hidden}>{hidden?'Show Coach':'Hide Coach'}</button></div>
  <div className="coach-guided-content">{children}</div>
  {!hidden&&spot.visible&&<div data-guide-ui className="coach-guide-layer" aria-hidden="true">
   <svg className="coach-guide-pointer" width="100%" height="100%">{phase!=='walking'&&<><path d={`M ${spot.x+size*.13} ${spot.y+size*.3} Q ${spot.x-12} ${spot.ty}, ${spot.tx} ${spot.ty}`} fill="none" stroke="var(--accent,#3159db)" strokeWidth="1.5" strokeDasharray="4 5" opacity=".45"/><circle cx={spot.tx} cy={spot.ty} r={spot.chart?9:16} fill="none" stroke="var(--accent,#3159db)" strokeWidth="2" className="coach-guide-ring"/></>}</svg>
   <div className="coach-guide-traveler" data-phase={phase} style={{transform:`translate(${spot.x}px,${spot.y}px)`,width:size,height:size*1.6}}><CoachRig phase={phase} motion={!paused&&!reduced} aim={(Math.atan2(spot.ty-(spot.y+size*.45),spot.tx-(spot.x+size*.43))*180/Math.PI+163+540)%360-180}/><span className="coach-guide-shadow"/></div>
  </div>}
 </div>;
}
