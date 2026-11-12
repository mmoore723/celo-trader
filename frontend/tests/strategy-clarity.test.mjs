import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { opportunityDecisionTitle, opportunityReason } from '../src/lib/opportunitySemantics.js';

test('unknown strategy IDs are not asserted to be retired', () => {
  const source = readFileSync(new URL('../src/pages/Journal.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /Retired historical strategy/);
  assert.match(source, /RESEARCH_FAILED_RANGE_V2: "Failed-Range Recovery"/);
});
test('strategy page defaults to trading and hides other groups', () => {
  const source = readFileSync(new URL('../src/pages/Settings.tsx', import.meta.url), 'utf8');
  assert.match(source, /useState<"trading" \| "paused" \| "research">\("trading"\)/);
  for (const group of ['trading', 'paused', 'research']) assert.ok(source.includes(`strategyView === "${group}" && <section`));
});
test('recorded previews do not claim a check is still running', () => {
  const entry = { lifecycle: 'pricing', entry_plan: { trigger: 'raw strategy setup detected' } };
  assert.equal(opportunityDecisionTitle(entry), 'Option preview recorded');
  assert.match(opportunityReason(entry), /did not save what happened next/);
  assert.equal(opportunityReason({ ...entry, reason_detail: 'Budget exceeded' }), 'Budget exceeded');
});
