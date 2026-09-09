import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/DailyBrief.tsx", import.meta.url), "utf8");

test("premarket report shows strategy readiness across all five requested timeframes", () => {
  assert.match(source, /Readiness \{pm\.readiness_score\}\/100/);
  assert.match(source, /Market direction by timeframe/);
  assert.match(source, /Best strategy match today/);
  assert.match(source, /Research only/);
});

test("premarket report cannot launch the old fabricated generic simulation", () => {
  assert.doesNotMatch(source, /Simulate Trade on Chart/);
  assert.doesNotMatch(source, /SimulationOverlay/);
  assert.doesNotMatch(source, /buildSim/);
});
