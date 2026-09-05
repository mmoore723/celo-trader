import test from "node:test";
import assert from "node:assert/strict";

import {
  currentVersionPerformance,
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

test("uses only exact current-version trades for the Settings proof line", () => {
  const current = currentVersionPerformance({
    strategy_id: "SPY",
    trades: 12,
    wins: 6,
    losses: 6,
    profit_factor: 0.54,
    current_version_trades: 2,
    current_version_wins: 2,
    current_version_losses: 0,
    current_version_total_pnl: 74,
    current_version_profit_factor: 0,
    prior_or_unversioned_trades: 10,
  });
  assert.equal(current.trades, 2);
  assert.equal(current.total_pnl, 74);
  assert.equal(strategyPerformanceState(current).pfLabel, "∞");
});
