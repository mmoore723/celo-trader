import assert from "node:assert/strict";
import test from "node:test";

import { premarketDayOutlook } from "../src/lib/premarketOutlook.js";

function ticker({ tradeable = true, score = 80, biases = ["up", "up", "up", "up", "flat"] } = {}) {
  return {
    tradeable_today: tradeable,
    readiness_score: score,
    timeframes: biases.map((bias, index) => ({ label: String(index), bias })),
  };
}

test("day outlook ignores every research-only ticker", () => {
  const result = premarketDayOutlook([
    ticker({ tradeable: false, score: 100 }),
    ticker({ tradeable: false, score: 100 }),
  ]);

  assert.equal(result.level, "waiting");
  assert.equal(result.tradableCount, 0);
});

test("two clear tradable tickers produce a green day", () => {
  const result = premarketDayOutlook([
    ticker({ score: 92 }),
    ticker({ score: 84, biases: ["down", "down", "down", "down", "flat"] }),
    ticker({ tradeable: false, score: 100 }),
  ]);

  assert.equal(result.level, "green");
  assert.equal(result.tradableCount, 2);
  assert.equal(result.clearCount, 2);
});

test("one clear tradable ticker produces a selective day", () => {
  const result = premarketDayOutlook([
    ticker({ score: 91 }),
    ticker({ score: 55, biases: ["up", "down", "flat", "flat", "flat"] }),
  ]);

  assert.equal(result.level, "yellow");
  assert.match(result.summary, /One tradable ticker/);
});

test("mixed weak tradable signals produce a red choppy day", () => {
  const result = premarketDayOutlook([
    ticker({ score: 58, biases: ["up", "up", "down", "down", "flat"] }),
    ticker({ score: 52, biases: ["down", "up", "down", "up", "flat"] }),
  ]);

  assert.equal(result.level, "red");
  assert.equal(result.mixedCount, 2);
  assert.match(result.summary, /mixed timeframe signals/);
});
