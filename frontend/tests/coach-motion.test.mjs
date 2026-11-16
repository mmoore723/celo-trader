import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source=fs.readFileSync(new URL('../src/components/learning/coachMotion.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {coachPose}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
test('walking is continuous, opposed hip motion with flexing knees',()=>{
 const a=coachPose(.1,'walking',0,true),b=coachPose(.1001,'walking',0,true);
 assert.equal(a.leftHip,-a.rightHip);assert.ok(a.leftHip!==0);assert.ok(a.rightKnee>0);
 for(const k of Object.keys(a))assert.ok(Math.abs(a[k]-b[k])<.1,k);
});
test('reduced motion freezes gait and breathing while retaining pointing',()=>{
 assert.deepEqual(coachPose(1,'pointing',20,false),coachPose(999,'pointing',20,false));
 assert.equal(coachPose(1,'pointing',20,false).arm,20);
 assert.equal(coachPose(1,'walking',20,false).leftHip,0);
});
test('pointing angles stay within the original artwork range',()=>{
 assert.equal(coachPose(0,'pointing',-100,true).arm,-45);
 assert.equal(coachPose(0,'pointing',100,true).arm,40);
});
