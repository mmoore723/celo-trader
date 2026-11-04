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
test('main learning page has one pair chooser and header omits watching ticker',()=>{
 const page=readFileSync(new URL('../src/pages/Playbooks.tsx',import.meta.url),'utf8');
 const topbar=readFileSync(new URL('../src/components/layout/Topbar.tsx',import.meta.url),'utf8');
 assert.equal((page.match(/<EnabledLearningPairs /g)||[]).length,1);
 assert.doesNotMatch(page,/<LearningHub /);
 assert.doesNotMatch(topbar,/Watching|status\.ticker/);
 const walkthrough=readFileSync(new URL('../src/components/playbooks/StrategyPlaybookExperience.tsx',import.meta.url),'utf8');
 assert.match(walkthrough,/activeCourses.length > 1 &&/);
});
