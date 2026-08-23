import test from "node:test";
import assert from "node:assert/strict";

import { expectedLearningAnswers, scoreLearningAnswer } from "../src/lib/learningSemantics.js";

test("scores valid directional examples without looking at future bars", () => {
  assert.deepEqual(expectedLearningAnswers("clean_win", "bullish"), ["call"]);
  assert.deepEqual(expectedLearningAnswers("valid_loss", "bearish"), ["put"]);
  assert.equal(scoreLearningAnswer("valid_loss", "bearish", "put"), true);
});

test("a valid losing setup is not retrospectively relabeled no-trade", () => {
  assert.equal(scoreLearningAnswer("valid_loss", "bullish", "call"), true);
  assert.equal(scoreLearningAnswer("valid_loss", "bullish", "reject"), false);
});

test("blocked and ambiguous examples teach waiting or rejection", () => {
  assert.deepEqual(expectedLearningAnswers("rejected_missing_condition", "bullish"), ["reject"]);
  assert.deepEqual(expectedLearningAnswers("false_breakout_or_chop", "bearish"), ["reject"]);
  assert.deepEqual(expectedLearningAnswers("ambiguous_no_trade", "bullish"), ["wait", "reject"]);
});
