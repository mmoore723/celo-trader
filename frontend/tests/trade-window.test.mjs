import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const sourceUrl = new URL("../src/components/charts/tradeWindow.ts", import.meta.url);
const source = await readFile(sourceUrl, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  fileName: sourceUrl.pathname,
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`;
const { tradeWindowBounds } = await import(moduleUrl);

const bars = Array.from({ length: 81 }, (_, minute) => ({
  time: new Date(Date.UTC(2026, 8, 9, 16, minute)).toISOString(),
  open: 1, high: 1, low: 1, close: 1, volume: 1,
}));

test("frames 20 one-minute candles before entry and after exit", () => {
  const bounds = tradeWindowBounds(
    bars, "2026-09-09T16:30:32.000Z", "2026-09-09T16:40:34.000Z",
  );
  assert.deepEqual(bounds, { startIndex: 10, endIndex: 61 });
  const visible = bars.slice(bounds.startIndex, bounds.endIndex);
  assert.equal(visible[0].time, "2026-09-09T16:10:00.000Z");
  assert.equal(visible.at(-1).time, "2026-09-09T17:00:00.000Z");
});

test("an open position keeps every available candle after entry", () => {
  assert.deepEqual(
    tradeWindowBounds(bars, "2026-09-09T16:30:32.000Z"),
    { startIndex: 10, endIndex: bars.length },
  );
});
