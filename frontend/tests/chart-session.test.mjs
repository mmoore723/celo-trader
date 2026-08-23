import test from "node:test";
import assert from "node:assert/strict";
import { openingRangeForBars } from "../src/lib/chartSession.js";

const bars = [{ time: "2026-08-20T14:45:00", close: 763.42 }];

test("rejects a stale opening range from a prior session", () => {
  assert.deepEqual(openingRangeForBars(bars, {
    time: "2026-08-19T09:30:00", bars: 3, high: 776.69, low: 775.36,
  }), {});
});

test("rejects an incomplete opening range", () => {
  assert.deepEqual(openingRangeForBars(bars, {
    time: "2026-08-20T09:30:00", bars: 2, high: 764.10, low: 762.80,
  }), {});
});

test("keeps a complete opening range from the displayed session", () => {
  assert.deepEqual(openingRangeForBars(bars, {
    time: "2026-08-20T09:30:00", bars: 3, high: 764.10, low: 762.80,
  }), { high: 764.10, low: 762.80 });
});

test("removes opening-range overlays when the toggle is off", () => {
  assert.deepEqual(openingRangeForBars(bars, {
    time: "2026-08-20T09:30:00", bars: 3, high: 764.10, low: 762.80,
  }, false), {});
});
