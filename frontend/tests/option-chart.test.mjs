import test from "node:test";
import assert from "node:assert/strict";
import { optionMetrics, quoteSegments } from "../src/lib/optionChart.ts";

const base = { option_type: "put", contracts: 2, entry_price: 4, stop_price: 3, target_price: 6,
  closed: false, quotes: [{ time: 100, bid: 4.1, ask: 4.3 }] };

test("bought calls and puts use bid times 100 times quantity, not underlying direction", () => {
  for (const option_type of ["call", "put"]) {
    const result = optionMetrics({ ...base, option_type }, 150);
    assert.ok(Math.abs(result.pnl-20) < 0.00001);
    assert.ok(Math.abs(result.value-820) < 0.00001);
    assert.equal(result.stale, false);
  }
});
test("old quotes stay historical; missing quotes do not invent value or profit", () => {
  assert.equal(optionMetrics(base, 221).stale, true);
  const missing = optionMetrics({ ...base, quotes: [] });
  assert.equal(missing.price, null);
  assert.equal(missing.pnl, null);
  assert.equal(missing.value, null);
});
test("closed trade uses actual fills and recorded pnl, including zero", () => {
  const result = optionMetrics({ ...base, closed: true, exit_price: 4, realized_pnl: 0 });
  assert.equal(result.pnl, 0);
  assert.equal(result.value, 800);
  assert.equal(result.stale, false);
});
test("inverted or missing reference levels do not become fake profit/loss boxes", () => {
  const result = optionMetrics({ ...base, target_price: 3, stop_price: 5 });
  assert.equal(result.target, null);
  assert.equal(result.stop, null);
});
test("quote gaps are not interpolated as continuous prices", () => {
  const quotes = [100, 160, 500, 560].map(time => ({ time, bid: 4, ask: 4.2 }));
  assert.deepEqual(quoteSegments(quotes), [quotes.slice(0, 2), quotes.slice(2)]);
});
