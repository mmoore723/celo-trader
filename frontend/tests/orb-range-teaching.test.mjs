import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';
const source=readFileSync(new URL('../src/components/playbooks/StrategyPlaybookExperience.tsx',import.meta.url),'utf8');
const chart=source.slice(source.indexOf('function CoachChart({'),source.indexOf('function TrendContinuationChart({'));
let code=ts.transpileModule('import {useState} from "react"; const POINTING_COACH_IMAGE="/coach-test.png"; export '+chart,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
for(const name of ['react','react/jsx-runtime']) code=code.replaceAll(JSON.stringify(name),JSON.stringify(import.meta.resolve(name)));
const {CoachChart}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
test('opening range uses first three candle wicks and extends both boundaries',()=>{
 const html=renderToStaticMarkup(createElement(CoachChart,{focus:0}));
 assert.match(html,/313\.25/); assert.match(html,/307\.09/);
 assert.match(html,/rest of the session/);
 assert.match(html,/highest wick/); assert.match(html,/lowest wick/);
 assert.match(html,/Show the high/); assert.match(html,/Show the low/);
 assert.match(html,/Coach Celo pointing at the opening-range high/);
 assert.equal((html.match(/x2="710"[^>]*stroke="#(?:135fc9|9d2479)"/g)||[]).length,2);
 assert.match(source,/setPointTo\("low"\)/);
});
test('opening range stays unchanged in later chart steps',()=>{
 for(const focus of [1,2,3,4]) {
  const html=renderToStaticMarkup(createElement(CoachChart,{focus}));
  assert.match(html,/HIGH \$313\.25/); assert.match(html,/LOW \$307\.09/);
 }
});
