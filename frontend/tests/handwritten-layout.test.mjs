import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const source = await readFile(new URL('../src/components/charts/handwrittenLayout.ts', import.meta.url),'utf8');
const compiled = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}});
const {referenceNotes,placeNote,intersects} = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString('base64')}`);
test('duplicate saved and position prices become one note without mutating evidence',()=>{
 const rows = [{type:'hline',price:690.09,label:'Setup invalidation',color:'red'}, {type:'hline',price:690.09,label:'Stock stop $690.09 | 9 contracts | R:R 1:2',color:'red'}, {type:'hline',price:689.16,label:'Entry trigger',color:'gold'}, {type:'hline',price:687.30,label:'Underlying target',color:'green'}];
 const before=JSON.stringify(rows); const notes=referenceNotes(rows);
 assert.equal(notes.length,3);assert.equal(notes[0].text,'Idea breaks here');
 assert.equal(JSON.stringify(rows),before); assert.ok(notes.every(n=>!n.text.includes('contracts')));
});
for(const width of [320,736,1200]) test(`labels avoid candles, marker lanes and each other at ${width}px`,()=>{
 const obstacles=[{x:width*.4,y:170,w:width*.6,h:230},{x:width*.65,y:0,w:90,h:600}];
 for(const y of [200,205,210,300,400]){
  const box=placeNote(width,600,y,180,obstacles);
  assert.ok(box);assert.ok(obstacles.every(o=>!intersects(box,o)));
  assert.ok(box.x>=0&&box.x+box.w<=width&&box.y+box.h<=600);obstacles.push(box);
 }
});
test('dense and offscreen views never force a label over prices',()=>{
 assert.equal(placeNote(320,400,200,200,[{x:0,y:0,w:320,h:400}]),null);
 assert.equal(placeNote(320,400,-10,200,[]),null);
 assert.equal(placeNote(150,400,200,200,[]),null);
});
