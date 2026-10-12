import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../src/lib/stockPositionDrawings.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { stockPositionDrawings } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
const trade = { id: 288, ticker: "SPY", option_type: "put", direction: "short", entry_price: 3.52,
  stop_price: 2.816, target_price: 5.28, contracts: 2, entry_time: "2026-10-12T12:55:16-04:00", exit_time: "2026-10-12T13:25:19-04:00" };
const setup = { ticker: "SPY", trade: { id: 288 }, setup_details: { v2_entry_reference: 777.71, v2_stop: 778.01, v2_target: 777.11 } };
test("stock put boxes use stock levels, bearish geometry and actual trade duration", () => {
  const rows = stockPositionDrawings(trade, setup);
  assert.equal(rows.length, 5);
  assert.ok(rows.every(r => r.ts === trade.entry_time && r.end_ts === trade.exit_time));
  const boxes = rows.filter(r => r.type === "zone");
  assert.deepEqual(boxes.map(r => [r.price_low, r.price_high]), [[777.11,777.71],[777.71,778.01]]);
  assert.match(rows[0].label, /R:R 1:2.00/);
  assert.ok(rows.every(r => (r.price ?? r.price_low) > 700));
});
test("calls put reward above entry and risk below", () => {
  const rows = stockPositionDrawings({ ...trade, direction:"long", option_type:"call" }, { ...setup, setup_details: { v2_entry_reference: 777, v2_stop: 776, v2_target: 779 } });
  assert.deepEqual(rows.filter(r=>r.type==='zone').map(r=>[r.price_low,r.price_high]),[[777,779],[776,777]]);
});
test("missing or another trade's setup never substitutes option dollars", () => {
  assert.deepEqual(stockPositionDrawings(trade), []);
  assert.deepEqual(stockPositionDrawings(trade, { ...setup, trade:{id:289} }), []);
  assert.deepEqual(stockPositionDrawings(trade, { ...setup, ticker:'QQQ' }), []);
});
test("hidden chart fits after positive width and option view defaults to one minute", async () => {
  const core = await readFile(new URL("../src/components/charts/chartCore.ts", import.meta.url), "utf8");
  assert.match(core,/if \(w <= 0\)/);
  assert.match(core,/if \(previousWidth <= 0\) chart.timeScale\(\).fitContent\(\)/);
  const option = await readFile(new URL("../src/components/charts/OptionPositionChart.tsx", import.meta.url), "utf8");
  assert.match(option,/useState<"daily" \| "1min">\("1min"\)/);
});
