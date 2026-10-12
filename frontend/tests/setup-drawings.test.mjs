import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../src/lib/setupDrawings.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { setupDrawings } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`);
const setup = { id: "qqq", strategy_id: "V2_AFTERNOON_COMPRESSION_BREAKOUT", trigger_bar: "2026-10-12T14:00:00-04:00" };
test("draws recorded compression levels and never option premium on the stock scale", () => {
  const rows = setupDrawings({ ...setup, contract: { ask: 2 }, setup_details: { compression_high: 745, compression_low: 742, underlying_stop: 746 } });
  assert.deepEqual(rows.map(r => r.price), [745, 742, 746]);
  assert.ok(rows.every(r => r.ts === setup.trigger_bar));
});
test("draws actual ORB, trend pullback and FVG evidence", () => {
  const rows = setupDrawings({ ...setup, setup_details: { or_high: 10, or_low: 9, pullback_low: 9.5, gap_upper: 9.9, gap_lower: 9.8 } });
  assert.equal(rows.filter(r => r.type === "hline").length, 5);
  assert.equal(rows.find(r => r.type === "zone").price_low, 9.8);
});
test("no invented levels when data is missing or invalid", () => {
  assert.deepEqual(setupDrawings(), []);
  assert.deepEqual(setupDrawings({ ...setup, setup_details: { or_high: null, or_low: "unknown", v2_stop: NaN, v2_target: -2 } }), []);
});
test("live chart removes Bands and Pos and connects setup cards to drawings", async () => {
  const live = await readFile(new URL("../src/pages/LiveTrading.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(live, /\["(?:Bands|Pos)"/);
  assert.match(live, /showVwapBands=\{false\}/);
  assert.match(live, /showPositionCard=\{false\}/);
  assert.match(live, /setSelectedSetup\(opportunity\)/);
  assert.match(live, /annotations=\{chartAnnotations\}/);
});

test("a blocked or unlinked setup cannot hide actual entry and exit markers", async () => {
  const live = await readFile(new URL("../src/pages/LiveTrading.tsx", import.meta.url), "utf8");
  const chart = live.slice(live.indexOf("<BoomerangReplay"), live.indexOf("narrationEvents={narrationEvents}"));
  assert.match(chart, /trades=\{tickerTrades\}/);
  assert.doesNotMatch(chart, /trades=\{chartSetup/);
  assert.match(chart, /annotations=\{chartAnnotations\}/);
});
