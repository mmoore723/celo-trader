import test from "node:test";
import assert from "node:assert/strict";

import { formatSignedCurrency } from "../src/lib/money.js";

test("keeps the minus sign on losses", () => {
  assert.equal(formatSignedCurrency(-640.9), "-$640.90");
});

test("shows an explicit plus sign on gains and zero", () => {
  assert.equal(formatSignedCurrency(47.41), "+$47.41");
  assert.equal(formatSignedCurrency(0), "+$0.00");
});
