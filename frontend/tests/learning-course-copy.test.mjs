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
