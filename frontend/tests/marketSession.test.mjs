import test from "node:test";
import assert from "node:assert/strict";

import { isTradingDayFinal, newYorkDateKey } from "../src/lib/marketSession.js";

test("keeps an intraday grade provisional until the New York close", () => {
  assert.equal(isTradingDayFinal(new Date("2026-09-01T16:00:00Z")), false);
  assert.equal(isTradingDayFinal(new Date("2026-09-01T20:00:00Z")), true);
});

test("uses the New York date near UTC midnight", () => {
  assert.equal(newYorkDateKey(new Date("2026-08-29T00:30:00Z")), "2026-08-28");
});

test("a completed weekend session is final", () => {
  assert.equal(isTradingDayFinal(new Date("2026-09-05T16:00:00Z")), true);
});
