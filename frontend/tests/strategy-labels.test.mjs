import test from 'node:test';
import assert from 'node:assert/strict';
import { strategyName, normalizeStrategyLabels } from '../src/lib/strategyIdentity.js';

test('canonical strategy names hide tickers and unify historical aliases', () => {
  for (const name of ['SPY Trend Continuation', 'RESEARCH_QQQ_TREND_V2', 'V2_SPY_TREND_CONT', 'V2_TREND_CONT', 'TREND_CONT']) {
    assert.equal(strategyName(name), 'Trend Continuation');
  }
  assert.equal(strategyName('TSLA Opening-Range Pullback'), 'Opening-Range Pullback');
  assert.equal(strategyName('V2_TSLA_TWO_LEG_TREND_PULLBACK'), 'Two-Leg Trend Pullback');
});

test('API label normalization preserves execution identity and evidence', () => {
  const source = {display_name:'SPY Trend Continuation', strategy_id:'V2_SPY_TREND_CONT',
    strategy_version:'research.1', evidence:'SPY Trend Continuation',
    nested:[{strategy_name:'TSLA Opening-Range Pullback'}]};
  const result=normalizeStrategyLabels(source);
  assert.equal(result.display_name,'Trend Continuation');
  assert.equal(result.strategy_id,source.strategy_id);
  assert.equal(result.strategy_version,source.strategy_version);
  assert.equal(result.evidence,source.evidence);
  assert.equal(result.nested[0].strategy_name,'Opening-Range Pullback');
  assert.equal(source.display_name,'SPY Trend Continuation');
});
