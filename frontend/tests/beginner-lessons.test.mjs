import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/components/playbooks/beginnerLessons.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {BEGINNER_LESSONS}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('each authored course has five explained steps and concrete examples',()=>{
 assert.deepEqual(Object.keys(BEGINNER_LESSONS).sort(),['v2_orb','v2_trend','v2_spy_fvg','v2_two_leg','v2_recovery'].sort());
 for(const steps of Object.values(BEGINNER_LESSONS)) {
   assert.equal(steps.length,5);
   for(const step of steps) {assert.ok(step.meaning.length>80); assert.ok(step.example.length>80);}
 }
});
test('lessons explain units without claiming chart lines guarantee bot exits',()=>{
 assert.match(BEGINNER_LESSONS.v2_recovery[1].example,/\$0.10/);
 assert.match(BEGINNER_LESSONS.v2_two_leg[2].example,/\$0.50 to \$2.50/);
 assert.match(BEGINNER_LESSONS.v2_orb[4].example,/Do not assume a drawn line automatically places a stop order/);
 const view=readFileSync(new URL('../src/components/playbooks/StrategyPlaybookExperience.tsx',import.meta.url),'utf8');
 assert.match(view,/beginner\?\.meaning \?\? step.lesson/);
 assert.match(view,/beginner\?\.example \?\? step.coach/);
 assert.doesNotMatch(view,/Explain more|\sxl:grid-cols-/);
});
