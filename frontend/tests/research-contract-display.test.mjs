import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8",
);

test("research results can be narrowed to one ticker", () => {
  assert.match(source, /type="search" placeholder="META"/);
  assert.match(source, /row\.pair\.ticker\.includes\(wantedTicker\)/);
});

test("research results separate no setup from no matching option", () => {
  assert.match(source, /Setup, no option/);
  assert.match(source, /No setup/);
  assert.match(source, /raw trigger/);
  assert.match(source, /distinct research play/);
  assert.match(source, /including overlapping plays/);
  assert.doesNotMatch(source, /`Waiting \(\$\{waiting\}\)`/);
});
const settingsSource = readFileSync(
  new URL("../src/pages/Settings.tsx", import.meta.url), "utf8",
);

test("promising research is green but remains distinct from working or enabled", () => {
  assert.match(source, /promising: \{ label: "Looks promising", color: "var\(--positive\)" \}/);
  assert.match(source, /working: \{ label: "Working", color: "var\(--positive\)" \}/);
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
  assert.match(source, /exitMeasurement\.pf_label/);
  assert.match(source, /Real exit:/);
  assert.match(source, /Not measured yet/);
  assert.match(source, /No losses yet/);
  assert.match(source, /Data since/);
  assert.match(source, /market days/);
  assert.match(source, /Earlier-version setups kept separate/);
});

test("strategy settings use distinct cards and explicit evidence dates", () => {
  assert.match(settingsSource, /Current research · strategy exits/);
  assert.match(settingsSource, /Tests through/);
  assert.match(settingsSource, /option result/);
  assert.match(settingsSource, /settings-card-grid/);
  assert.doesNotMatch(settingsSource, /Past test/);
  assert.doesNotMatch(settingsSource, /May place orders on the tickers above/);
  assert.doesNotMatch(settingsSource, /RESEARCH ONLY · No orders/);
  assert.doesNotMatch(settingsSource, /Tests every collected ticker; cannot place orders/);
  assert.match(settingsSource, /Data collected since/);
  assert.match(settingsSource, /20 non-overlapping completed tests/);
});
