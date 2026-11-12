import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const src=await readFile(new URL('../src/components/charts/marketStructure.ts',import.meta.url),'utf8');
const js=ts.transpileModule(src,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {detectSwings,structureLabels}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const bar=(i,h,l=h-2,c=(h+l)/2)=>({time:new Date(Date.UTC(2026,10,11,14,30+i)).toISOString(),open:c,high:h,low:l,close:c,volume:100});
test('pivot waits for right candles to close, never marked at original peak',()=>{
 const b=[1,2,3,4,5,10,5,4,3,2,1,2].map((v,i)=>bar(i,v));
 assert.equal(detectSwings(b.slice(0,11)).length,0);
 const s=detectSwings(b).find(s=>s.kind==='SH');
 assert.equal(s.idx,5);assert.equal(s.confirmedIdx,11);
 assert.equal(s.time,b[11].time);assert.equal(s.pivotTime,b[5].time);
});
test('forming last candle cannot create break or alter confirmed swings',()=>{
 const b=Array.from({length:80},(_,i)=>bar(i,100+Math.sin(i/3)*5+i/30));
 const before=structureLabels(b);
 const changed=b.map((v,i)=>i===b.length-1?{...v,high:9999,low:-9999,close:9999}:v);
 assert.deepEqual(structureLabels(changed),before);
});
test('extending history across old adaptive thresholds preserves all earlier labels',()=>{
 const b=Array.from({length:410},(_,i)=>bar(i,100+Math.sin(i/3)*5+Math.sin(i/19)*8));
 const full=structureLabels(b);
 for(const n of [50,99,100,199,200,399,400]){
  assert.deepEqual(structureLabels(b.slice(0,n)),full.filter(x=>x.time<=b[n-1].time));
 }
 assert.ok(full.some(x=>x.text==='Bearish CHoCH'));
 assert.ok(full.some(x=>x.text==='Bullish CHoCH'));
 assert.ok(full.filter(x=>x.text.includes('CHoCH')).every(x=>x.event));
 assert.ok(full.filter(x=>x.text.startsWith('HH')).every(x=>!x.event && x.direction==='up'));
});
test('markers use causal labels and suppress unverified legacy structure annotations',async()=>{
 const m=await readFile(new URL('../src/components/charts/chartMarkers.ts',import.meta.url),'utf8');
 assert.match(m,/structureLabels\(input.bars/);
 assert.doesNotMatch(m,/length >= 400/);
 assert.match(m,/if \(isStructureAnnotation\) continue/);
});
