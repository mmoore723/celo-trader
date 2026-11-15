import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const rows=JSON.parse(readFileSync(new URL('../src/components/learning/historicalRetests.json',import.meta.url)));
test('historical exercises preserve valid consecutive candles and causal breaks',()=>{
 assert.equal(rows.length,16);assert.equal(new Set(rows.map(e=>e.id)).size,16);
 for(const e of rows){
  const mins=b=>Number(b.time.split(':')[0])*60+Number(b.time.split(':')[1]);
  e.bars.forEach((b,i)=>{assert.ok(b.low<=Math.min(b.open,b.close));assert.ok(b.high>=Math.max(b.open,b.close));if(i)assert.equal(mins(b)-mins(e.bars[i-1]),1);});
  assert.ok(e.touches.every(n=>n<e.breakCandle));const br=e.bars[e.breakCandle-1];assert.ok(e.direction==='bullish'?br.close>e.high:br.close<e.low);
  const last=e.bars.at(-1);assert.ok(last.high>=e.low&&last.low<=e.high);
 }
});
test('inside-zone followups retain precise closes without later bars',()=>{
 const original=rows.find(e=>e.id==='tsla-zone-close-practice'),e18=rows.find(e=>e.id==='tsla-zone-followup-18'),e19=rows.find(e=>e.id==='tsla-zone-followup-19');
 assert.equal(original.bars.length,17);assert.equal(e18.bars.length,18);assert.equal(e19.bars.length,19);
 assert.deepEqual(e19.bars.slice(0,18),e18.bars);assert.deepEqual(e18.bars.slice(0,17),original.bars);
 assert.equal(original.bars.at(-1).close,393.435);assert.equal(e18.bars.at(-1).close,393.47);assert.equal(e19.bars.at(-1).close,393.53);
 assert.ok(e18.bars.at(-1).close<e18.high);assert.ok(e19.bars.at(-1).close>e19.high);
});
