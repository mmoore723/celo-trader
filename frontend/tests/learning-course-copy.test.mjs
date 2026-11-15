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
let candleCode=ts.transpileModule(read('components/learning/CandlePractice.tsx'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
for(const name of ['react','react/jsx-runtime']) candleCode=candleCode.replaceAll(JSON.stringify(name),JSON.stringify(import.meta.resolve(name))).replaceAll("'"+name+"'",JSON.stringify(import.meta.resolve(name)));
const candleModule='data:text/javascript;base64,'+Buffer.from(candleCode).toString('base64');
const {CandlePractice,CandleAnatomy,candleParts,candleAnswers,candleWalkthrough}=await import(candleModule);
let visualCode=ts.transpileModule(read('components/learning/VisualPractice.tsx'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
visualCode=visualCode.replace(/import \{ CoachCelo \} from ['"]\.\/CoachCelo['"];?/,"const CoachCelo=({children})=>children;");
for(const name of ['react','react/jsx-runtime']) visualCode=visualCode.replaceAll(JSON.stringify(name),JSON.stringify(import.meta.resolve(name))).replaceAll("'"+name+"'",JSON.stringify(import.meta.resolve(name)));
const visualModule='data:text/javascript;base64,'+Buffer.from(visualCode).toString('base64');
const {VisualPractice,TeachingDiagram,practiceChoices}=await import(visualModule);
let workshopCode=ts.transpileModule(read('components/learning/LessonWorkshop.tsx'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
workshopCode=workshopCode.replaceAll("'./VisualPractice'",JSON.stringify(visualModule)).replaceAll('"./VisualPractice"',JSON.stringify(visualModule));
workshopCode=workshopCode.replaceAll("'./CandlePractice'",JSON.stringify(candleModule)).replaceAll('"./CandlePractice"',JSON.stringify(candleModule));
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

test('candle practice teaches correct body and wick geometry on green and red candles',()=>{
 const candles=lessons[6].workshop.candlePractice;
 assert.equal(candles.length,4);
 assert.ok(candles.some(c=>c.close>c.open)&&candles.some(c=>c.close<c.open));
 candles.forEach((c,i)=>{
  const p=candleParts(c),answers=candleAnswers(c,i);
  assert.ok(p.upper>0&&p.lower>0&&p.body>0);
  assert.equal(p.upper+p.body+p.lower,p.range);
  assert.equal(answers.filter(a=>a.correct).length,1);
  assert.equal(new Set(answers.map(a=>a.text)).size,3);
  assert.ok(candleWalkthrough(c).every(s=>s.title&&s.text.length>100));
  for(let focus=-1;focus<=3;focus++){
   const html=renderToStaticMarkup(createElement(CandleAnatomy,{candle:c,focus}));
   assert.doesNotMatch(html,/NaN|undefined|Infinity/);
   for(const [part,index] of [['body',0],['upper-wick',1],['lower-wick',2]])
    assert.equal(html.includes('data-part="'+part+'"'),focus===index||focus===3);
   for(const n of [c.open,c.high,c.low,c.close])assert.ok(html.includes('$'+n.toFixed(2)));
  }
 });
 assert.deepEqual(candleParts(candles[1]),{body:3,upper:1,lower:2,range:6});
 const html=renderToStaticMarkup(createElement(CandlePractice,{candles}));
 assert.match(html,/Read this candle/);assert.match(html,/How big is the body/);
 assert.doesNotMatch(html,/data-part=|trace the parts/,'initial question has no answer highlights');
 assert.doesNotMatch(read('components/learning/CandlePractice.tsx'),/fetch\(|api\.post|localStorage|sessionStorage/);
});


test('every lesson has distinct visual practice, step highlights and a fresh retry',()=>{
 for(const lesson of lessons){
  const scenes=lesson.workshop.visualPractice;assert.equal(scenes.length,2,lesson.id);
  assert.notDeepEqual(scenes[0],scenes[1],lesson.id);
  for(const [index,s] of scenes.entries()){
   assert.equal(new Set(s.choices).size,3);assert.ok(s.correct>=0&&s.correct<s.choices.length);
   assert.equal(practiceChoices(s,index).filter(a=>a.correct).length,1);
   const v=s.visual;assert.ok(v.labels.length>0);assert.equal(s.steps.length,3);
   assert.ok(s.steps.every(st=>st.text.length>20&&st.focus.length&&st.focus.every(i=>i>=0&&i<v.labels.length)),lesson.id);
   if(v.kind!=='flow'){
    assert.equal((v.values??v.bars).length,v.labels.length);
    assert.ok((v.values??v.bars.flatMap(b=>Object.values(b))).every(Number.isFinite));
    if(v.bars)assert.ok(v.bars.every(b=>b.high>=Math.max(b.open,b.close)&&b.low<=Math.min(b.open,b.close)));
   }
   const initial=renderToStaticMarkup(createElement(TeachingDiagram,{scene:s}));
   assert.doesNotMatch(initial,/data-highlighted="true"|NaN|undefined|Infinity/);
   for(let step=0;step<s.steps.length;step++){
    const html=renderToStaticMarkup(createElement(TeachingDiagram,{scene:s,step}));
    assert.equal((html.match(/data-highlighted="true"/g)??[]).length,s.steps[step].focus.length);
    assert.doesNotMatch(html,/NaN|undefined|Infinity/);
   }
  }
  const html=renderToStaticMarkup(createElement(VisualPractice,{scenes}));
  assert.match(html,/Show me why|Reveal next candles/);assert.doesNotMatch(html,/Not quite|Next highlight/);
  const coaching=renderToStaticMarkup(createElement(VisualPractice,{scenes,startWithWalkthrough:true}));
  assert.match(coaching,/same idea in a worked example|Next highlight/);
 }
});

test('visual practice money and reference examples have consistent independent arithmetic',()=>{
 const s=n=>lessons[n-1].workshop.visualPractice;
 assert.deepEqual(s(1).map(x=>x.visual.values),[[125,250],[250,750]]);
 assert.deepEqual(s(3).map(x=>x.visual.values),[[500,400],[200,300]]);
 assert.deepEqual(s(10).map(x=>[x.visual.bars[5].close>x.visual.reference,x.correct]),[[false,0],[true,0]]);
 assert.deepEqual(s(17).map(x=>x.visual.values.map(v=>v<x.visual.reference)),[[true,false],[true,false]]);
 for(const n of [18,39]) for(const x of s(n)){const [entry,peak,trail]=x.visual.values;assert.ok(Math.abs(trail-(entry+(peak-entry)*.75))<1e-10);}
 for(const n of [20,40,46,47])for(const x of s(n)){const [a,b,net]=x.visual.values;assert.ok(Math.abs(a+b-net)<1e-8);}
 for(const x of s(49)){const [baseline,candidate,difference]=x.visual.values;assert.equal(candidate-baseline,difference);}
 assert.deepEqual(s(41).map(x=>x.visual.values),[[2,1],[3,2]]);
 assert.deepEqual(s(38).map(x=>x.visual.values),[[7,3,1,6],[5,2,1,4]]);
});

test('missed saved checks and chart challenges connect to visual coaching, without changing scoring',()=>{
 const portal=read('components/learning/LearningPortal.tsx'),foundations=read('components/learning/Foundations.tsx'),visual=read('components/learning/VisualPractice.tsx');
 assert.match(portal,/!r.correct&&related\?\.workshop\?\.visualPractice/);
 assert.match(portal,/q.prompt===item.questions\[i\].prompt/);
 assert.match(portal,/startWithWalkthrough/);
 assert.match(foundations,/feedback&&i===step/);
 assert.match(foundations,/Try a different example of this skill/);
 assert.doesNotMatch(visual,/fetch\(|localStorage|sessionStorage|api\.|setInterval|setTimeout/);
 assert.match(visual,/setAnswer\(null\);setChecked\(false\);setStep\(0\)/);
 assert.match(visual,/useId/);
});

 test('visual coaching responds to available panel width, not just screen width', () => {
 const css=readFileSync(new URL('../src/components/learning/portal.css',import.meta.url),'utf8');
 assert.match(css,/container-type:inline-size/);
 assert.match(css,/@container\(min-width:660px\)/);
 assert.match(css,/@media\(max-width:1100px\)\{\.portal-layout\{grid-template-columns:1fr/);
 });

test('support and resistance form before later candles are revealed',()=>{
 for(const s of lessons[9].workshop.visualPractice){
  assert.deepEqual(s.buildup.map(b=>b.count),[2,4,5,6]);
  assert.equal(s.visual.referenceAt,4);
  const early=renderToStaticMarkup(createElement(TeachingDiagram,{scene:s,revealCount:2}));
  assert.doesNotMatch(early,/Reference |<th scope="row">[3456]<\/th>/);
  const established=renderToStaticMarkup(createElement(TeachingDiagram,{scene:s,revealCount:4}));
  assert.match(established,/Reference /);
  assert.doesNotMatch(established,/<th scope="row">[56]<\/th>/);
  const v=s.visual; const support=v.reference===80;
  assert.ok(support?v.bars[4].close>v.reference:v.bars[4].close<v.reference);
  assert.ok(support?v.bars[5].close<v.reference:v.bars[5].close>v.reference);
 }
});

test('chart setup practice reveals context before signals and hides future candle values',()=>{
 for(const n of [8,9,10,11,12,19,25,26,27,28,29,30])for(const s of lessons[n-1].workshop.visualPractice){
  assert.equal(s.visual.kind,'candles');assert.ok(s.visual.bars.length>=4);
  assert.ok(s.buildup.length>=3);assert.equal(s.buildup.at(-1).count,s.visual.bars.length);
  let last=0;for(const stage of s.buildup){assert.ok(stage.count>last);last=stage.count;assert.ok(stage.text.length>40);
   const html=renderToStaticMarkup(createElement(TeachingDiagram,{scene:s,revealCount:stage.count}));
   assert.equal((html.match(/scope="row"/g)||[]).length,stage.count);
   if(s.visual.referenceAt&&stage.count<s.visual.referenceAt)assert.doesNotMatch(html,/>Reference /);
  }
  const html=renderToStaticMarkup(createElement(VisualPractice,{scenes:[s]}));assert.match(html,/Build the setup first/);assert.doesNotMatch(html,/type="radio"/);
 }
});
