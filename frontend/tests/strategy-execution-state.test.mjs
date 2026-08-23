import test from "node:test";
import assert from "node:assert/strict";
import { strategyExecutionState } from "../src/lib/strategyExecutionState.js";

test("enabled paper strategy reports paper execution rather than shadow observation", () => {
  assert.deepEqual(strategyExecutionState({
    account_mode: "paper",
    execution_enabled: true,
    live_eligible: false,
  }, true), {
    badge: "PAPER EXECUTION ON",
    tone: "green",
    detail: "can execute in this paper account",
  });
});

test("paper strategy in a live account reports zero live order authority", () => {
  assert.deepEqual(strategyExecutionState({
    account_mode: "live",
    execution_enabled: false,
    live_eligible: false,
  }, true), {
    badge: "SHADOW ONLY IN LIVE",
    tone: "yellow",
    detail: "evaluating setups with zero live-order authority",
  });
});

test("disabled switch is explicit about being off", () => {
  assert.equal(strategyExecutionState({
    account_mode: "paper",
    execution_enabled: false,
    live_eligible: false,
  }, false).badge, "PAPER READY · OFF");
});
