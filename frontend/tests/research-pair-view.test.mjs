import assert from "node:assert/strict";
import test from "node:test";
import {
  profitFactorText, researchActionLabel, researchPairVisible, researchProfitFactorText, sortResearchPairs,
} from "../src/lib/researchPairView.js";

const pair = (overrides = {}) => ({
  ticker: "SPY", status: "collecting", diagnosis: "more_data",
  setups: 0, option_results: 0, ...overrides,
});

test("the normal results view shows only priced results", () => {
  assert.equal(researchPairVisible(pair(), "results"), false);
  assert.equal(researchPairVisible(pair({ setups: 3 }), "results"), false);
  assert.equal(researchPairVisible(pair({ setups: 3, option_results: 1 }), "results"), true);
});

test("needs-attention shows only a pair with an actionable diagnosis", () => {
  assert.equal(researchPairVisible(pair({ diagnosis: "entry" }), "attention"), true);
  assert.equal(researchPairVisible(pair({ diagnosis: "more_data" }), "attention"), false);
});

test("working and promising pairs sort ahead of collecting pairs", () => {
  const rows = [
    { pair: pair({ ticker: "AAPL" }), strategy: { display_name: "Alpha" } },
    { pair: pair({ ticker: "SPY", status: "working", option_results: 20 }), strategy: { display_name: "Beta" } },
    { pair: pair({ ticker: "QQQ", status: "promising", option_results: 5 }), strategy: { display_name: "Gamma" } },
  ];
  assert.deepEqual(sortResearchPairs(rows).map(row => row.pair.ticker), ["SPY", "QQQ", "AAPL"]);
});

test("plain labels explain PF and the next action", () => {
  assert.equal(profitFactorText("infinite"), "∞");
  assert.equal(profitFactorText(1.567), "1.57");
  assert.equal(researchProfitFactorText("infinite", 1), "No losses yet");
  assert.equal(researchProfitFactorText(null, 0), "Waiting");
  assert.equal(researchActionLabel("contract_exit"), "Test option + exit");
  assert.equal(researchActionLabel("early_loss"), "Losing — review");
});

test("an early losing pair appears in needs attention", () => {
  assert.equal(researchPairVisible(pair({ status: "losing_so_far", diagnosis: "early_loss", option_results: 5 }), "attention"), true);
});

test("PF 1.5 filter reflects the number instead of a delayed status label", () => {
  assert.equal(researchPairVisible(pair({ option_results: 2, profit_factor: 1.7 }), "passing"), true);
  assert.equal(researchPairVisible(pair({ status: "promising", option_results: 8, profit_factor: 1.2 }), "passing"), false);
});

test("a ticker watched for 20 days with no setup needs an entry-gate experiment", () => {
  assert.equal(researchPairVisible(pair({ diagnosis: "no_setups", market_days: 20 }), "attention"), true);
  assert.equal(researchPairVisible(pair({ diagnosis: "no_setups", market_days: 4 }), "attention"), false);
});
