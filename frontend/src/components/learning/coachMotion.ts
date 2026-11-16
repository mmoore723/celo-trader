export type CoachMotion = 'idle' | 'walking' | 'turning' | 'pointing';
// Continuous joint angles, not a sequence of replacement pictures.
export function coachPose(time:number, phase:CoachMotion, aim:number, motion:boolean){
 const stride=motion&&phase==='walking'?Math.sin(time*9):0;
 return {
  leftHip:stride*12,rightHip:-stride*12,
  leftKnee:Math.max(0,-stride)*17,rightKnee:Math.max(0,stride)*17,
  arm:phase==='pointing'?Math.max(-45,Math.min(40,aim)):-62+stride*9,
  elbow:phase==='pointing'?0:8+stride*5,
  rearArm:-stride*10,
  head:phase==='pointing'?-3:motion?Math.sin(time*.8)*1.4:0,
  lift:motion?(phase==='walking'?-Math.abs(stride)*6:Math.sin(time*1.7)*1.5):0,
  turn:phase==='walking'?.94:phase==='pointing'?.97:1,
 };
}
