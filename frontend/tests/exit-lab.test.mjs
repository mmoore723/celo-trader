import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const lab = readFileSync(new URL('../src/pages/ExitLab.tsx', import.meta.url), 'utf8');
const research = readFileSync(new URL('../src/pages/Research.tsx', import.meta.url), 'utf8');

test('Exit Lab is lazy and mounts only its selected subtab', () => {
  assert.match(research, /lazy\(\(\) => import\('\.\/ExitLab'\)/);
  assert.match(research, /tab === 'results' \? <Results[^\n]+: <Lab/);
});
test('Exit Lab uses account-scoped summaries and requests trades on demand', () => {
  assert.match(lab, /active_broker_account_id/);
  assert.match(lab, /queryKey: \['exit-lab', scope\]/);
  assert.match(lab, /queryKey: \['exit-lab-detail', scope/);
  assert.match(lab, /queryKey: \['exit-lab-trades', scope/);
  assert.match(lab, /enabled: showTrades/);
  assert.match(lab, /refetchIntervalInBackground: false/);
  assert.doesNotMatch(lab, /useMutation|method: ['"]POST|submit_order|runBacktest/);
});
test('charts and unknown evidence remain separated and labeled', () => {
  assert.match(lab, /chart.filter\(row => row.candidate_id === candidate\)/);
  assert.match(lab, /Paper evidence is not live validation/);
  assert.match(lab, /No complete paired series has been published/);
  assert.match(lab, /paper_policy \?\? 'Unverified'/);
});
