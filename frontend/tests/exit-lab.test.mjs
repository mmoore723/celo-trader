import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
const lab = readFileSync(new URL('../src/pages/ExitLab.tsx', import.meta.url), 'utf8');
const research = readFileSync(new URL('../src/pages/Research.tsx', import.meta.url), 'utf8');

test('Exit Lab is lazy and mounts only its selected subtab', () => {
  assert.match(research, /lazy\(\(\) => import\('\.\/ExitLab'\)/);
  assert.match(research, /tab === 'results' \? <Results[^\n]+: tab === 'exits' \? <Lab \/> : <Coverage \/>/);
  assert.match(research, /lazy\(\(\) => import\('\.\/CaptureCoverage'\)/);
});

test('coverage reports measured delay without starting research or disguising unknowns', () => {
  const coverage = readFileSync(new URL('../src/pages/CaptureCoverage.tsx', import.meta.url), 'utf8');
  assert.match(coverage, /Longest observed option refresh gap/);
  assert.match(coverage, /v == null \? 'Not measured'/);
  assert.match(coverage, /Receipt timing does not prove fresh contract prices/);
  assert.match(coverage, /No timing samples yet. This is not zero delay/);
  assert.doesNotMatch(coverage, /useMutation|method: ['"]POST|submit_order|runBacktest/);
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
