import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const source = readFileSync(
  new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8",
);

test("research results expose strategy-ticker contract policy evidence", () => {
  assert.match(source, /Most option evidence/);
  assert.match(source, /Which option choice is working\?/);
  assert.match(source, /contract_tests/);
  assert.match(source, /Rows using a different option test/);
});
