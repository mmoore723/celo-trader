import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { inJournalWindow, journalDate, journalRealizedSummary } from "../src/lib/journalWindow.js";

const now = new Date("2026-10-15T18:00:00Z");
test("journal defaults to today without restricting status to open trades", () => {
  const source = readFileSync(new URL("../src/pages/Journal.tsx", import.meta.url), "utf8");
  assert.match(source, /useState<DateWindow>\("today"\)/);
  assert.match(source, /useState<"all" \| "open" \| "closed">\("all"\)/);
});
const aapl = { id: 291, entry_time: "2026-10-14T09:51:00.642337", exit_time: "2026-10-15T09:30:57.285680", status: "closed", pnl: -150 };
test("trade 291 closed today remains visible despite yesterday entry", () => {
  assert.equal(inJournalWindow(aapl, "today", "", now), true);
  assert.equal(inJournalWindow({ ...aapl, exit_time: "2026-10-14T10:00:00" }, "today", "", now), false);
});
test("open entries today remain visible", () => {
  assert.equal(inJournalWindow({ entry_time: "2026-10-15T10:00:00" }, "today", "", now), true);
});
test("UTC midnight is still previous New York date and offset-free records remain ET", () => {
  assert.equal(journalDate("2026-10-16T01:00:00Z"), "2026-10-15");
  assert.equal(journalDate("2026-10-15T23:00:00"), "2026-10-15");
  assert.equal(journalDate("2026-01-16T04:00:00Z"), "2026-01-15");
  assert.equal(journalDate("invalid"), null);
});
test("7 and 30 days use calendar date boundaries including today", () => {
  assert.equal(inJournalWindow({ entry_time: "2026-10-09T04:00:00" }, "week", "", now), true);
  assert.equal(inJournalWindow({ entry_time: "2026-10-08T23:59:00" }, "week", "", now), false);
  assert.equal(inJournalWindow({ entry_time: "2026-09-16T04:00:00" }, "month", "", now), true);
  assert.equal(inJournalWindow({ entry_time: "2026-09-15T23:59:00" }, "month", "", now), false);
});
test("custom includes exit date and rejects future or unknown dates", () => {
  assert.equal(inJournalWindow(aapl, "custom", "2026-10-15", now), true);
  assert.equal(inJournalWindow({}, "today", "", now), false);
  assert.equal(inJournalWindow({ entry_time: "2026-10-16T10:00:00" }, "today", "", now), false);
});
test("realized totals exclude open, missing and nonfinite results", () => {
  assert.deepEqual(journalRealizedSummary([aapl, { status: "open", pnl: 500 }, { status: "closed", pnl: null }, { status: "closed", pnl: NaN }]), { pnl: -150, closed: 1, winRate: 0 });
  assert.deepEqual(journalRealizedSummary([]), { pnl: 0, closed: 0, winRate: null });
});
