import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/components/charts/executionGrade.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 } });
const { gradeBar, gradeBeforeEntry } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
const bar = (minute, extra = {}) => ({ time: `2026-10-12T18:${minute}:00Z`, open: 100, high: 102, low: 99, close: 100.1, atr: 4, rvol: 0.5, volume: 10, ...extra });
const strong = bar("01", { close: 102, atr: 2, rvol: 2 });

test("grades the last completed candle, not the first chart candle or unfinished entry candle", () => {
  const bars = [bar("00"), strong, bar("02")];
  assert.equal(gradeBeforeEntry(bars, "2026-10-12T18:02:20Z").grade, "strong");
  assert.equal(gradeBeforeEntry(bars, "2026-10-12T18:02:00Z").grade, "strong");
  assert.equal(gradeBeforeEntry(bars.toReversed(), "2026-10-12T14:02:20-04:00").grade, "strong");
});

test("does not invent a weak grade from missing or invalid indicators", () => {
  for (const extra of [{ atr: undefined }, { rvol: undefined }, { atr: 0 }, { atr: NaN }, { close: NaN }]) {
    assert.equal(gradeBar(bar("00", extra)), null);
  }
  assert.equal(gradeBar(bar("00")).grade, "weak");
});

test("missing prior candles, empty charts and dates outside the view have no grade", () => {
  const bars = [bar("00"), bar("01"), bar("04")];
  for (const date of ["bad", "2026-10-12T17:59:00Z", "2026-10-12T18:04:20Z", "2026-10-13T18:05:00Z"])
    assert.equal(gradeBeforeEntry(bars, date), null);
  assert.equal(gradeBeforeEntry([], "2026-10-12T18:02:00Z"), null);
  assert.equal(gradeBeforeEntry([strong], "2026-10-12T18:02:00Z"), null);
});

test("uses completed five-minute candles on five-minute charts", () => {
  assert.equal(gradeBeforeEntry([bar("00"), { ...strong, time: bar("05").time }, bar("10")], "2026-10-12T18:10:30Z").grade, "strong");
});

test("entry marker distinguishes candle grade from strategy strength", async () => {
  const markers = await readFile(new URL("../src/components/charts/chartMarkers.ts", import.meta.url), "utf8");
  assert.match(markers, /gradeBeforeEntry\(input.bars, t.entry_time\)/);
  assert.match(markers, /prior candle:/);
  assert.doesNotMatch(markers, /BUY \(\$\{grade.grade\}\)/);
});
