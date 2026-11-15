import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
const read = path => readFileSync(new URL('../src/'+path, import.meta.url),'utf8');
test('course pages omit research grades and duplicate technical block',()=>{
 const pair=read('components/learning/PairLearning.tsx');
 const page=read('pages/Playbooks.tsx');
 const chart=read('components/playbooks/StrategyPlaybookExperience.tsx');
 assert.doesNotMatch(pair,/Research evidence|Research baseline|data\.evidence/);
 assert.doesNotMatch(page,/Research status:|Technical reference \(optional\)|GLOBAL_PARAMS/);
 assert.doesNotMatch(chart,/EVIDENCE_LABELS|evidence\.label/);
 assert.doesNotMatch(chart,/Explain more/);
 assert.match(chart,/min-w-\[760px\]/);
 assert.match(chart,/grid-cols-\[minmax\(0,1fr\)_320px\]/);
});
let code=ts.transpileModule(read('components/learning/VersionRuleWalkthrough.tsx'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
for(const name of ['react','react/jsx-runtime']) code=code.replaceAll(JSON.stringify(name),JSON.stringify(import.meta.resolve(name))).replaceAll("'"+name+"'",JSON.stringify(import.meta.resolve(name)));
const {VersionRuleWalkthrough}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('lesson starts with one idea and optional explanations without losing exact rules',()=>{
 const html=renderToStaticMarkup(createElement(VersionRuleWalkthrough,{version:'v2',steps:['Wait for a finished candle.'],exit:'Exit after 30 minutes.',selectedPolicy:false}));
 assert.match(html,/Wait for the setup, not the excitement/);
 assert.match(html,/Its close is the last price/);
 assert.match(html,/For example:/);
 assert.match(html,/Wait for a finished candle/);
 assert.doesNotMatch(html,/<details|Explain more|Research baseline|broker fill|policy/);
});
let workshopCode=ts.transpileModule(read('components/learning/LessonWorkshop.tsx'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
workshopCode=workshopCode.replace(/import \{ CoachCelo \} from ['"]\.\/CoachCelo['"];?/,"const CoachCelo=({children})=>children;");
for(const name of ['react','react/jsx-runtime']) workshopCode=workshopCode.replaceAll(JSON.stringify(name),JSON.stringify(import.meta.resolve(name))).replaceAll("'"+name+"'",JSON.stringify(import.meta.resolve(name)));
const {LessonWorkshop}=await import('data:text/javascript;base64,'+Buffer.from(workshopCode).toString('base64'));
const lessons=JSON.parse(readFileSync(new URL('../../api/routes/learning_course_content.json',import.meta.url),'utf8'));
test('opening lessons teach distinct steps and test a new application without replacing saved progress',()=>{
 for(const lesson of lessons.slice(0,4)){
  const w=lesson.workshop;assert.equal(w.steps.length,4);assert.equal(new Set(w.steps.map(s=>s.title)).size,4);
  assert.ok(w.steps.every(s=>s.explain.length>120&&s.example.length>100));
  assert.ok(w.challenge.correct>=0&&w.challenge.correct<w.challenge.choices.length);
  assert.notEqual(w.challenge.prompt,lesson.questions[0].prompt);
  const html=renderToStaticMarkup(createElement(LessonWorkshop,{workshop:w,onReview:()=>{}}));
  assert.match(html,/By the end:/);assert.match(html,/Walk through it/);assert.match(html,/Try a new situation/);
  assert.ok(html.includes(w.steps[0].title));assert.ok(!html.includes(w.steps[3].explain));
 }
 assert.match(read('components/learning/LearningPortal.tsx'),/current\.workshop/);
 assert.equal(lessons.length,50);
});
