import test from 'node:test';
import assert from 'node:assert/strict';
import { exitReason } from '../src/lib/strategyIdentity.js';
test('all eight research exit names retain their exact thresholds', () => {
 for (const n of [2,5,15,20,25]) assert.equal(exitReason(`premium_${n}pct`),`${n}% Premium Gain`);
 for (const n of [15,20,25]) assert.equal(exitReason(`giveback_${n}pct`),`${n}% Peak-Profit Giveback`);
});
test('shared events never invent historical policy percentages', () => {
 for (const r of ['trend_partial_profit','stage1_trend_profit_profit_take','trend_profit_giveback']) assert.ok(!exitReason(r).includes('%'));
 assert.equal(exitReason('adverse_3x5m_10pct_loss'),'3-Candle / 10% Loss Fail-Safe');
});
test('timers, session exits and missing evidence use consistent factual names', () => {
 assert.equal(exitReason('v2_spy_trend_paid_markout_30m (held=30.1min)'),'30-Minute Time Limit');
 assert.equal(exitReason('selected_test_90m'),'90-Minute Time Limit');
 assert.equal(exitReason('research_time_cap_120m'),'120-Minute Time Limit');
 assert.equal(exitReason('research_session_close'),'Session Close');
 assert.equal(exitReason('session_hard_cutoff_355pm'),'Session Close');
 assert.equal(exitReason(null),'Exit reason not recorded');
 assert.equal(exitReason('reconciliation_never_filled'),'Reconciled: Entry Never Filled');
});
