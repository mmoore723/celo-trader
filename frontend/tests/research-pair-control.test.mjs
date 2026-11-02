import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../src/components/research/ResearchPairControl.tsx', import.meta.url), 'utf8');
const page = readFileSync(new URL('../src/pages/ScannerOpportunities.tsx', import.meta.url), 'utf8');
test('research pair action carries exact strategy, version and ticker', () => {
  assert.match(page, /<ResearchRow strategyId=\{strategy.strategy_id\}/);
  assert.match(page, /ResearchPairControl strategyId=\{strategyId\} version=\{strategyVersion\} ticker=\{pair.ticker\}/);
  assert.match(source, /strategy_id: strategyId, strategy_version: version, ticker, enabled: true/);
});
test('admin pair action requires explicit confirmation and preserves existing endpoint', () => {
  assert.match(source, /if \(!user\?\.is_admin\) return null/);
  assert.match(source, /Turn on pair/);
  assert.match(source, /Confirm turn on/);
  assert.match(source, /\/api\/settings\/strategies\/admin-override/);
  assert.match(source, /if \(busy\) return/);
  assert.match(source, /does not enable live trading/);
  assert.doesNotMatch(source, /paper_trading:|risk_pct:|submit_order|useEffect/);
});
test('errors remain visible and research refreshes after successful save', () => {
  assert.match(source, /role="alert"/);
  assert.match(source, /strategy-research-results/);
  assert.match(source, /strategy-research-analytics/);
});
test('test choices use a modal and cannot silently enable unsupported policies', () => {
  assert.match(source, /createPortal\(<dialog/);
  assert.match(source, /node.showModal\(\)/);
  assert.match(source, /onCancel=/);
  assert.match(source, /pair.exit_comparison/);
  assert.match(source, /pair.contract_tests/);
  assert.match(source, /if \(researchOnly \|\| trading\) return/);
  assert.match(source, /disabled=\{busy \|\| researchOnly \|\| trading\}/);
  assert.match(source, /Selecting two tests is not evidence/);
});
