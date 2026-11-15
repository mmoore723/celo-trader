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

test('all remaining lessons teach the skill with a distinct worked example and two practice tasks',()=>{
 const prompts=new Set();
 for(const lesson of lessons.slice(4)){
  const w=lesson.workshop;
  assert.equal(w.steps.length,3,lesson.id);
  assert.ok(w.steps.every(s=>s.title&&s.explain.length>100&&s.example.length>75),lesson.id);
  assert.ok(w.goal&&w.mistake&&w.application.prompt&&w.application.answer);
  assert.ok(!prompts.has(w.challenge.prompt));prompts.add(w.challenge.prompt);
  assert.notEqual(w.challenge.prompt,lesson.questions[0].prompt);
  assert.ok(w.challenge.correct>=0&&w.challenge.correct<w.challenge.choices.length);
  assert.ok(w.visual);
  const html=renderToStaticMarkup(createElement(LessonWorkshop,{workshop:w,onReview:()=>{}}));
  assert.match(html,/Illustrative teaching example/);
  assert.doesNotMatch(html,/NaN|undefined|Infinity/);
  assert.ok(!html.includes(w.application.answer),'answer stays hidden until practice');
 }
});
const {LessonVisual,revealedCandles}=await import('data:text/javascript;base64,'+Buffer.from(workshopCode).toString('base64'));
test('visual data and incremental candle bounds do not disclose later observations',()=>{
 for(const lesson of lessons.slice(4)){
  const v=lesson.workshop.visual;
  if(v.kind==='table'){assert.ok(v.rows.every(r=>r.length===v.headers.length));continue;}
  if(v.kind==='line'){assert.equal(v.labels.length,v.values.length);assert.ok(v.values.every(Number.isFinite));continue;}
  assert.equal(v.bars.length,v.labels.length);assert.equal(v.notes.length,v.bars.length);
  assert.ok(v.bars.every(b=>b.high>=Math.max(b.open,b.close)&&b.low<=Math.min(b.open,b.close)));
  const visible=revealedCandles(v,1);assert.equal(visible.bars.length,1);
  const altered={...v,bars:[v.bars[0],{open:9000,high:9001,low:8999,close:9000}]};
  assert.deepEqual(revealedCandles(altered,1),visible,'future data does not change displayed scale');
  const html=renderToStaticMarkup(createElement(LessonVisual,{visual:v}));
  assert.ok(html.includes(v.notes[0]));assert.ok(!html.includes(v.notes.at(-1)));
  assert.match(html,/Next candle/);
  assert.doesNotMatch(html,/NaN|undefined|Infinity/);
 }
 // Candle fundamentals have no invented support level or zero-price axis.
 const plain=revealedCandles(lessons[6].workshop.visual,1);
 assert.equal(plain.minimum,49);assert.equal(plain.maximum,52);
});
test('worked expiration payoffs match contract math and the shared practice has no account writes',()=>{
 const call=lessons[5].workshop.visual;
 assert.deepEqual(call.values,[49,50,51,52,53,54].map(s=>(Math.max(s-50,0)-2)*100));
 const spread=lessons[44].workshop.visual;
 assert.deepEqual(spread.values,[48,50,52,53,55,57].map(s=>(Math.max(s-50,0)-Math.max(s-55,0)-3)*100));
 const covered=lessons[45].workshop.visual;
 assert.deepEqual(covered.values,[40,45,48,50,55,65].map(s=>(s-50+2-Math.max(s-55,0))*100));
 assert.doesNotMatch(read('components/learning/LessonWorkshop.tsx'),/fetch\(|api\.post|localStorage|sessionStorage/);
 assert.match(read('components/learning/LessonWorkshop.tsx'),/self-check practice/);
});
test('lesson numbers and timestamps retain readable decimal and clock formatting',()=>{
 for(const l of lessons.slice(4))assert.doesNotMatch(JSON.stringify(l.workshop),/\d[.:] \d/,l.id);
});
