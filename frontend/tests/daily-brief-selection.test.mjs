import test from "node:test";
import assert from "node:assert/strict";
import { preferredDailyBriefTicker } from "../src/lib/dailyBriefSelection.js";

test("does not select a scanner result while preferred data is still loading", () => {
  assert.equal(preferredDailyBriefTicker({
    selected: "",
    loading: true,
    pinnedTickers: [],
    premarketTickers: [],
    scannerTickers: ["ABBV"],
  }), "");
});

test("selects the first configured watchlist ticker after data settles", () => {
  assert.equal(preferredDailyBriefTicker({
    selected: "",
    loading: false,
    pinnedTickers: ["SPY", "QQQ"],
    premarketTickers: ["ABBV", "SPY"],
    scannerTickers: ["ABBV"],
  }), "SPY");
});

test("preserves a valid manual selection and replaces a stale one", () => {
  const input = {
    loading: false,
    pinnedTickers: ["SPY"],
    premarketTickers: ["SPY", "ABBV"],
    scannerTickers: [],
  };
  assert.equal(preferredDailyBriefTicker({ ...input, selected: "ABBV" }), "ABBV");
  assert.equal(preferredDailyBriefTicker({ ...input, selected: "TSLA" }), "SPY");
});
