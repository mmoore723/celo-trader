import {useEffect,useId,useRef} from 'react';
import art from '../../assets/learning/coach-celo-pointing.png';
import {coachPose,type CoachMotion} from './coachMotion';

/** Original artwork articulated at joints. No frame switching or generated replacement face. */
export function CoachRig({phase,aim,motion}:{phase:CoachMotion;aim:number;motion:boolean}){
 const svg=useRef<SVGSVGElement>(null),id=useId().replace(/:/g,'');
 const currentPose=useRef(coachPose(0,'idle',0,false));
 const state=useRef({phase,aim,motion});state.current={phase,aim,motion};
 useEffect(()=>{
  let frame=0,last=0;const pose=currentPose.current;
  const draw=(now:number)=>{
   const s=state.current,target=coachPose(now/1000,s.phase,s.aim,s.motion);
   const blend=s.motion?1-Math.exp(-Math.min(64,now-last)/120):1;last=now;
   for(const k of Object.keys(pose) as (keyof typeof pose)[])pose[k]+=(target[k]-pose[k])*blend;
   const set=(part:string,value:string)=>svg.current?.querySelector(`[data-joint="${part}"]`)?.setAttribute('transform',value);
   set('body',`translate(0 ${pose.lift}) translate(650 800) scale(${pose.turn} 1) translate(-650 -800)`);
   set('head',`rotate(${pose.head} 650 390)`);
   set('arm',`rotate(${pose.arm} 425 445)`);set('elbow',`rotate(${pose.elbow} 265 410)`);
   set('rearArm',`rotate(${pose.rearArm} 820 650)`);
   set('leftHip',`rotate(${pose.leftHip} 540 1040)`);set('rightHip',`rotate(${pose.rightHip} 710 1040)`);
   set('leftKnee',`rotate(${pose.leftKnee} 504 1230)`);set('rightKnee',`rotate(${pose.rightKnee} 740 1250)`);
   if(s.motion)frame=requestAnimationFrame(draw);
  };
  frame=requestAnimationFrame(draw);return()=>cancelAnimationFrame(frame);
 },[motion,phase,aim]);
 const piece=(name:string)=><use href={`#${id}-art`} clipPath={`url(#${id}-${name})`}/>;
 const clips:Record<string,string>={
  head:'475,0 900,0 900,390 745,415 560,405 475,330',
  torso:'425,390 550,380 625,410 740,385 845,435 895,650 805,690 795,865 820,1090 620,1125 425,1100 440,865 450,520 380,510',
  upperArm:'265,345 430,390 435,500 260,450',
  forearm:'25,290 270,345 275,450 50,445',
  rearArm:'775,650 895,640 900,1050 745,1050 760,875',
  leftThigh:'430,1080 610,1080 565,1250 455,1250',
  leftShin:'455,1220 565,1220 585,1505 295,1520 315,1340',
  rightThigh:'620,1090 805,1080 815,1270 690,1270',
  rightShin:'690,1240 815,1240 850,1586 610,1586 630,1370',
 };
 return <svg ref={svg} className="coach-rig" viewBox="0 0 992 1586" aria-hidden="true"><defs><image id={`${id}-art`} href={art} width="992" height="1586"/>{Object.entries(clips).map(([name,points])=><clipPath id={`${id}-${name}`} key={name}><polygon points={points}/></clipPath>)}</defs><g data-joint="body"><g data-joint="rightHip">{piece('rightThigh')}<g data-joint="rightKnee">{piece('rightShin')}</g></g><g data-joint="leftHip">{piece('leftThigh')}<g data-joint="leftKnee">{piece('leftShin')}</g></g><g data-joint="rearArm">{piece('rearArm')}</g>{piece('torso')}<g data-joint="head">{piece('head')}</g><g data-joint="arm">{piece('upperArm')}<g data-joint="elbow">{piece('forearm')}</g></g></g></svg>;
}
