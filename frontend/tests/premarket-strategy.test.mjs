import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/DailyBrief.tsx", import.meta.url), "utf8");

test("premarket report shows strategy fit across all five requested timeframes", () => {
  assert.match(source, /Match \{pm\.readiness_score\}\/100/);
  assert.match(source, /Market direction by timeframe/);
  assert.match(source, /Best fit today/);
  assert.match(source, /Research only/);
});

test("premarket list contains only complete reports and explains descending scores", () => {
  assert.match(source, /Best matches first, from 100 down/);
  assert.doesNotMatch(source, /The live scanner found this ticker/);
  assert.doesNotMatch(source, /scanner-only extras/);
});

test("premarket report cannot launch the old fabricated generic simulation", () => {
  assert.doesNotMatch(source, /Simulate Trade on Chart/);
  assert.doesNotMatch(source, /SimulationOverlay/);
  assert.doesNotMatch(source, /buildSim/);
});
