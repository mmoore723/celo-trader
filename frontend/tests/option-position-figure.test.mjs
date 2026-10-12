import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../src/lib/optionPositionFigure.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { optionPositionFigure } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
const base = { trade_id: 1, mode: "paper", contract_symbol: "SPY261016P00770000", option_type: "put",
  entry_price: 4, stop_price: 3, target_price: 6, contracts: 2, entry_time: 1788530417,
  exit_time: 1788532271, exit_price: 5, closed: true, as_of: 1788533000, interval: "1min",
  candles: [{ time: 1788530400, open: 4, high: 5, low: 3.8, close: 4.5 }] };
test("exact option candles, two boxes, actual fills not rounded to candle times", () => {
  const { traces, layout } = optionPositionFigure(base);
  assert.equal(traces[0].type, "candlestick");
  assert.equal(traces[0].name, base.contract_symbol);
  assert.deepEqual(traces[0].open, [4]);
  assert.equal(layout.shapes.filter(s => s.type === "rect").length, 2);
  assert.equal(layout.shapes.filter(s => s.type === "line").length, 3);
  assert.notEqual(traces[1].x[0], traces[0].x[0]);
  assert.match(traces[1].x[0], /10:00:17/);
  assert.match(traces[2].x[0], /10:31:11/);
  assert.equal(layout.shapes[0].x0, traces[1].x[0]);
  assert.equal(layout.shapes[0].x1, traces[2].x[0]);
  assert.match(layout.annotations[0].text, /50.0%.*400.00.*Qty 2.*1:2.00/);
  assert.match(layout.annotations[1].text, /-25.0%.*-200.00/);
});
test("purchased puts have the same premium risk/reward geometry as calls", () => {
  assert.deepEqual(optionPositionFigure(base).layout.shapes, optionPositionFigure({ ...base, option_type: "call" }).layout.shapes);
});
test("open positions extend boxes to as-of and never invent an exit fill", () => {
  const result = optionPositionFigure({ ...base, closed: false, exit_time: null, exit_price: null });
  assert.equal(result.traces.length, 2);
  assert.match(result.layout.shapes[0].x1, /10:43:20/);
});
test("missing or underlying-scale levels produce no fabricated risk/reward box", () => {
  const result = optionPositionFigure({ ...base, stop_price: 750, target_price: null });
  assert.equal(result.layout.shapes.length, 1);
  assert.match(result.layout.annotations[0].text, /R:R unavailable/);
});
test("daily history is labeled and keeps separate zoom state", () => {
  const result = optionPositionFigure({ ...base, interval: "daily" });
  assert.match(result.layout.xaxis.title.text, /Daily option candles/);
  assert.match(result.layout.uirevision, /daily/);
});
