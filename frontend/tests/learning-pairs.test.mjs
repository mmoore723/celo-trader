import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read = name => readFileSync(new URL(`../src/components/learning/${name}.tsx`,import.meta.url),'utf8');
test('enabled learning pairs use a compact searchable selector and scoped links',()=>{
 const source=read('EnabledLearningPairs');
 assert.match(source,/aria-label="Learning pair"/);
 assert.match(source,/Find a learning pair/);
 assert.match(source,/learningLink\(selected.strategy_id,selected.ticker,selected.version,view\)/);
 assert.doesNotMatch(source,/<details/);
});
test('trade practice separates real rows, fictional samples and scanner observations',()=>{
 const source=read('TradePractice');
 assert.match(source,/data.actual/);
 assert.match(source,/data.samples/);
 assert.match(source,/Samples are fictional and never counted as trade results/);
 assert.match(read('PairLearning'),/not necessarily executed trades/);
});
