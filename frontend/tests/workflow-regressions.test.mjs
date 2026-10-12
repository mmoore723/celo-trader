import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const read = name => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('login preserves account identity and server Terms decision', () => {
  const login = read('pages/Login.tsx');
  assert.match(login, /user_id: data.user_id/);
  assert.match(login, /terms_accepted: data.terms_accepted === true/);
});
test('setup checks supported credential flags and rejects failed responses', () => {
  const app = read('App.tsx');
  assert.match(app, /if \(!r.ok\) throw/);
  assert.match(app, /d.has_alpaca === false && d.has_tradier === false && d.has_tradier_market === false/);
});
test('profit goal is default and precedes needs work', () => {
  const page = read('pages/ScannerOpportunities.tsx');
  assert.match(page, /researchFilter, setResearchFilter\] = useState\("passing"\)/);
  assert.match(page, /\[\["passing", `At profit goal .*?\["attention", `Needs work/);
  assert.doesNotMatch(page, /Setup, no option/);
});
test('research-only action is not blocked by browser confirmation dialogs', () => {
  const component = read('components/settings/StrategyRecommendations.tsx');
  assert.doesNotMatch(component, /action === "research_only" && !window.confirm/);
  assert.match(component, /action === "enable" && !window.confirm/);
});
