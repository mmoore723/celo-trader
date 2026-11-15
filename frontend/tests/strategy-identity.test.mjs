import { test } from "node:test";
import assert from "node:assert/strict";
import { strategyName, strategyVariant, strategyVersion } from "../src/lib/strategyIdentity.js";

test("strategy titles separate ticker scope without erasing technical names", () => {
  assert.equal(strategyName("SPY Trend Continuation"), "Trend Continuation");
  assert.equal(strategyName("TSLA Two-Leg Trend Pullback"), "Two-Leg Trend Pullback");
  assert.equal(strategyName("VWAP Pullback (1-Hour KER)"), "VWAP Pullback (1-Hour KER)");
  assert.equal(strategyName("New strategy"), "New strategy");
});

test("different Trend Continuation rules remain distinguishable", () => {
  assert.equal(strategyVariant("V2_SPY_TREND_CONT"), "30-minute exit");
  assert.equal(strategyVariant("V2_TREND_CONT"), "Structure-based exit");
  assert.equal(strategyVersion("vresearch.1"), "vresearch.1");
  assert.equal(strategyVersion("2.1.0"), "v2.1.0");
  assert.equal(strategyVersion(), "");
});

test('fail-safe labels use the recorded candle interval', async () => {
  const { exitReason } = await import('../src/lib/strategyIdentity.js');
  assert.equal(exitReason('adverse_3x4m_10pct_loss'), '3-Candle / 10% Loss Fail-Safe (4-minute candles)');
  assert.equal(exitReason('adverse_3x5m_10pct_loss'), '3-Candle / 10% Loss Fail-Safe');
});
