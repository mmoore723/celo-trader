import test from "node:test";
import assert from "node:assert/strict";
import { preferredDailyBriefTicker } from "../src/lib/dailyBriefSelection.js";

test("does not select a scanner result while preferred data is still loading", () => {
  assert.equal(preferredDailyBriefTicker({
    selected: "",
    loading: true,
    premarketTickers: [],
  }), "");
});

test("selects the highest-ranked completed premarket report after data settles", () => {
  assert.equal(preferredDailyBriefTicker({
    selected: "",
    loading: false,
    premarketTickers: ["ABBV", "SPY"],
  }), "ABBV");
});

test("preserves a valid manual selection and replaces a stale one", () => {
  const input = {
    loading: false,
    premarketTickers: ["SPY", "ABBV"],
  };
  assert.equal(preferredDailyBriefTicker({ ...input, selected: "ABBV" }), "ABBV");
  assert.equal(preferredDailyBriefTicker({ ...input, selected: "TSLA" }), "SPY");
});
