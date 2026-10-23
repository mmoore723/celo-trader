import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components/settings/WeeklyExitAudit.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');

test('weekly audit keeps detailed results collapsed and grid lazy', () => {
  assert.match(source, /<details><summary[^>]*>Validation and candidate results/);
  assert.match(source, /<details><summary[^>]*>Assumptions and limitations/);
  assert.match(source, /showGrid && <Results/);
  assert.match(source, /slice\(0, 1\)/);
});

test('weekly audit contains scrolling and dims underlying visualizations', () => {
  assert.match(source, /max-h-\[85dvh\] overflow-auto/);
  assert.match(css, /overscroll-behavior: contain/);
  assert.match(css, /\.weekly-exit-dialog::backdrop/);
});
