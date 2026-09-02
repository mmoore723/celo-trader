import test from "node:test";
import assert from "node:assert/strict";

import {
  strategyPerformanceForId,
  strategyPerformanceState,
} from "../src/lib/strategyPerformance.js";

test("maps actual performance to the exact strategy id", () => {
  const rows = [
    { strategy_id: "A", trades: 10, wins: 6, losses: 4, profit_factor: 1.7 },
    { strategy_id: "B", trades: 20, wins: 12, losses: 8, profit_factor: 2.1 },
  ];
  assert.equal(strategyPerformanceForId(rows, "B")?.profit_factor, 2.1);
  assert.equal(strategyPerformanceForId(rows, "C"), null);
});

test("does not call a tiny high-PF sample validated", () => {
  const result = strategyPerformanceState({
    trades: 5, wins: 4, losses: 1, profit_factor: 6.73,
  });
  assert.equal(result.pfLabel, "6.73");
  assert.equal(result.enoughEvidence, false);
  assert.equal(result.meetsTarget, false);
});

test("labels all-win and empty samples honestly", () => {
  assert.equal(strategyPerformanceState({
    trades: 30, wins: 30, losses: 0, profit_factor: 0,
  }).pfLabel, "∞");
  assert.equal(strategyPerformanceState(null).pfLabel, "not recorded");
});
