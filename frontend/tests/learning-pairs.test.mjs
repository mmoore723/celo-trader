import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read = name => readFileSync(new URL(`../src/components/learning/${name}.tsx`,import.meta.url),'utf8');
test('learning starts with strategy families and versions, not ticker search',()=>{
 const source=read('EnabledLearningPairs');
 assert.match(source,/aria-label="Strategy family"/);
 assert.match(source,/aria-label="Strategy variation"/);
 assert.doesNotMatch(source,/Find a ticker|Choose a pair|<input/);
 assert.match(source,/<PairLearning/);
 assert.match(read('PairLearning'),/activeLessonIds=\{\[lessons\[data.source\]\]\}/);
 assert.match(read('PairLearning'),/Protection and position sizing/);
});
test('trade practice separates real rows, fictional samples and scanner observations',()=>{
 const source=read('TradePractice');
 assert.match(source,/data.actual/);
 assert.match(source,/data.samples/);
 assert.match(source,/Samples are fictional and never counted as trade results/);
 assert.match(read('PairLearning'),/not necessarily executed trades/);
});
test('main learning page has one pair chooser and header omits watching ticker',()=>{
 const page=readFileSync(new URL('../src/pages/Playbooks.tsx',import.meta.url),'utf8');
 const topbar=readFileSync(new URL('../src/components/layout/Topbar.tsx',import.meta.url),'utf8');
 assert.equal((page.match(/<EnabledLearningPairs /g)||[]).length,1);
 assert.doesNotMatch(page,/<LearningHub /);
 assert.doesNotMatch(topbar,/Watching|status\.ticker/);
 const walkthrough=readFileSync(new URL('../src/components/playbooks/StrategyPlaybookExperience.tsx',import.meta.url),'utf8');
 assert.match(walkthrough,/activeCourses.length > 1 &&/);
});
