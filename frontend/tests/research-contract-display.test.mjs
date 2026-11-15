import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8",
);

test("research results can be narrowed to one ticker", () => {
  assert.match(source, /type="search" placeholder="META"/);
  assert.match(source, /setDebouncedTicker\(tickerSearch\.trim\(\)\.toUpperCase\(\)\)/);
  assert.match(source, /ticker: debouncedTicker/);
});

test("research results separate no setup from no matching option", () => {
  assert.match(source, /Signals without priced results/);
  assert.match(source, /No setup/);
  assert.match(source, /raw trigger/);
  assert.match(source, /distinct research play/);
  assert.match(source, /including overlapping plays/);
  assert.doesNotMatch(source, /`Waiting \(\$\{waiting\}\)`/);
});
const settingsSource = readFileSync(
  new URL("../src/pages/Settings.tsx", import.meta.url), "utf8",
);

test("green research status requires qualification and remains separate from trading", () => {
  assert.match(source, /pair\.recommendation\?\.qualified/);
  assert.match(source, /label: "Research qualified", color: "var\(--positive\)"/);
  assert.match(source, /label: "Not yet qualified", color: "var\(--warning\)"/);
  assert.match(source, /pair\.tradable \? "TRADING ON" : "TESTING"/);
});

test("research results expose strategy-ticker contract policy evidence", () => {
  assert.match(source, /Next experiment/);
  assert.match(source, /Evidence and test plan/);
  assert.match(source, /Which option choice is working\?/);
  assert.match(source, /contract_tests/);
  assert.match(source, /Rows using a different option test/);
});

test("research results distinguish dated tests from the current strategy version", () => {
  assert.match(source, /Tests through/);
  assert.match(source, /All-results PF/);
  assert.match(source, /QualificationEvidence evidence=\{pair\.recommendation\}/);
  assert.match(source, /Real exit:/);
  assert.match(source, /Not measured yet/);
  assert.match(source, /No losses yet/);
  assert.match(source, /Data since/);
  assert.match(source, /market days/);
  assert.match(source, /Earlier-version setups kept separate/);
});

test("research evidence stays in Research, not Settings", () => {
 assert.doesNotMatch(settingsSource, /Research results and test evidence|ResearchTargetTickers|TestedStrategies|researchMatrix/);
 assert.match(settingsSource, /<TradingOverview/);
});
