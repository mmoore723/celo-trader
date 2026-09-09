import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8",
);
const settingsSource = readFileSync(
  new URL("../src/pages/Settings.tsx", import.meta.url), "utf8",
);

test("research results expose strategy-ticker contract policy evidence", () => {
  assert.match(source, /Next experiment/);
  assert.match(source, /Evidence and test plan/);
  assert.match(source, /Which option choice is working\?/);
  assert.match(source, /contract_tests/);
  assert.match(source, /Rows using a different option test/);
});

test("research results distinguish dated tests from the current strategy version", () => {
  assert.match(source, /Tests through/);
  assert.match(source, /Current PF/);
  assert.match(source, /Data since/);
  assert.match(source, /market days/);
  assert.match(source, /Earlier-version setups kept separate/);
});

test("strategy settings use distinct cards and explicit evidence dates", () => {
  assert.match(settingsSource, /Results since/);
  assert.match(settingsSource, /Tests through/);
  assert.match(settingsSource, /option result/);
  assert.match(settingsSource, /grid gap-3 lg:grid-cols-2/);
  assert.doesNotMatch(settingsSource, /Past test/);
  assert.doesNotMatch(settingsSource, /May place orders on the tickers above/);
  assert.doesNotMatch(settingsSource, /RESEARCH ONLY · No orders/);
  assert.doesNotMatch(settingsSource, /Tests every collected ticker; cannot place orders/);
  assert.match(settingsSource, /Data collected since/);
  assert.match(settingsSource, /days with option results/);
});
