import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { resolveStrategyIdentity } from "./strategy-identity-loader.mjs";

const source = readFileSync(new URL("../src/components/research/ResearchAnalyticsView.tsx", import.meta.url), "utf8");
let code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext } }).outputText;
for (const name of ["react/jsx-runtime", "react"]) code = code.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name)));
const { ResearchAnalyticsView } = await import(`data:text/javascript;base64,${Buffer.from(resolveStrategyIdentity(code)).toString("base64")}`);
const data = { summary: { profit_factor: null, win_rate_pct: null, net_pnl: 0, active_tests: 0 }, pipeline: { raw_triggers: 0, distinct_plays: 0, priced_results: 0, completed_tests: 0 }, data_quality: { tracked_tests: 0, affected_tests: 0, affected_pct: null, covered_pairs: 0, total_pairs: 0 }, pairs: [], tickers: [] };
const render = value => renderToStaticMarkup(createElement(ResearchAnalyticsView, { data: value }));

test("analytics renders empty evidence without a fake quality percentage", () => {
  const html = render(data);
  assert.match(html, /No pairs match these filters/);
  assert.match(html, /Not measured/);
  assert.doesNotMatch(html, /NaN|Infinity|undefined/);
});

test("pair progress stays paginated and preserves version, health and target evidence", () => {
  const pairs = Array.from({ length: 26 }, (_, index) => ({ ticker: `T${index}`, strategy_id: "ONE", strategy_name: "Example", version: "vresearch.2", status: "at_goal", independent_tests: 12, target_tests: 20, completed_tests: 15, priced_tests: 15, win_rate_pct: 60, profit_factor: 1.8, typical_profit: 8, net_pnl: 100, health_available: true, missing_candles: 2, missing_quotes: 3, late_entry_prices: 1, pending_quotes: 0, target_2r_hits: 4 }));
  const html = render({ ...data, pairs });
  assert.match(html, /12 \/ 20/);
  assert.match(html, /vresearch.2/);
  assert.match(html, /4 recorded 2R target exits/);
  assert.match(html, /2 missing candles \/ 3 missing quotes/);
  assert.match(html, /Page 1 of 2/);
  assert.doesNotMatch(html, /<strong>T25<\/strong>/);
  assert.match(html, /Minimum 10 priced tests/);
});

test("leaderboard uses the unique ranked API list, not mirrored top and bottom rows", () => {
  const html = render({ ...data, tickers: [{ ticker: "META", priced_tests: 3, win_rate_pct: 66.7, net_pnl: 40 }] });
  assert.equal((html.match(/META/g) || []).length, 1);
  assert.match(html, /\+\$40.00/);
});
