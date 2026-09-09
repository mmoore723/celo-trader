import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const sourceUrl = new URL("../src/lib/optionChart.ts", import.meta.url);
const source = await readFile(sourceUrl, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  fileName: sourceUrl.pathname,
});
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`;
const { optionMetrics, quoteSegments } = await import(moduleUrl);
const optionPlot = await readFile(new URL("../src/components/charts/OptionPricePlot.tsx", import.meta.url), "utf8");
const tradeChart = await readFile(new URL("../src/components/charts/TradeChart.tsx", import.meta.url), "utf8");
const overlays = await readFile(new URL("../src/components/charts/chartOverlays.ts", import.meta.url), "utf8");
const chartCore = await readFile(new URL("../src/components/charts/chartCore.ts", import.meta.url), "utf8");

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

test("position view uses the standard candle chart with a non-distorting position overlay", () => {
  assert.match(optionPlot, /import \{ TradeChart \} from "\.\/TradeChart"/);
  assert.match(optionPlot, /bars=\{bars\}/);
  assert.match(optionPlot, /trades=\{\[chartTrade\]\}/);
  assert.match(optionPlot, /positionLevelsOnCandleScale/);
  assert.match(optionPlot, /minuteTimelineEnd=/);
  assert.doesNotMatch(optionPlot, /<svg/);
  assert.match(tradeChart, /positionLevelsOnCandleScale/);
  assert.match(overlays, /position_reward/);
  assert.match(overlays, /position_risk/);
  assert.match(overlays, /Math\.min\(pl\.target, candleHigh\)/);
  assert.match(overlays, /inVisibleCandleRange/);
  assert.match(overlays, /referenceAnchor/);
  assert.match(chartCore, /if \(disposed \|\| !mainEl\.current\) return/);
  assert.match(chartCore, /disposed = true;\s*ro\.disconnect\(\)/);
  assert.match(chartCore, /Whitespace carries no price or volume/);
  assert.match(chartCore, /minute \+= 60/);
});
