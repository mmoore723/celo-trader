import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { resolveStrategyIdentity } from "./strategy-identity-loader.mjs";
const source = readFileSync(new URL("../src/components/settings/StrategyRecommendations.tsx", import.meta.url), "utf8");
let compiled = ts.transpileModule(source, {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext}}).outputText;
for (const name of ["react", "react-dom", "react/jsx-runtime"]) compiled = compiled.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name)));
const {StrategyRecommendations} = await import(`data:text/javascript;base64,${Buffer.from(resolveStrategyIdentity(compiled)).toString("base64")}`);
const render = recommendations => renderToStaticMarkup(createElement(StrategyRecommendations, {recommendations, onDecision: async () => {}}));
const fixture = {strategy_id: "TEST", ticker: "META", strategy_version: "1", display_name: "VWAP", account_mode: "paper", fingerprint: "f", profit_factor: .7, completed_trades: 10, net_pnl: -30,
  evidence: {training: {profit_factor: 2}, validation: {profit_factor: 1.7}}};
test("General has separate new-match and active-review panels with trade-based triggers", () => {
  const html = render([]);
  assert.match(html, /New strategy matches/);
  assert.match(html, /Review active strategies/);
  assert.match(html, /20 non-overlapping completed tests/);
  assert.match(html, /latest 10 non-overlapping completed research tests/);
  assert.match(html, /No minimum day count/);
});
test("a losing active pair offers research-only or keep-trading without an enable action", () => {
  const html = render([{...fixture, kind: "review_active"}]);
  assert.match(html, /Move to research only/);
  assert.match(html, /Keep trading/);
  assert.match(html, /PF 0.70/);
  assert.doesNotMatch(html, /Turn on ·/);
  assert.match(html, /not broker fills/);
});
test("qualified research without an execution adapter never offers a working enable button", () => {
  const html = render([{...fixture, kind: "new_match", can_enable: false, blocker: "Execution implementation needed"}]);
  assert.match(html, /Execution implementation needed/);
  assert.match(html, /Why unavailable\?/);
  assert.doesNotMatch(html, /Turn on ·/);
  assert.doesNotMatch(html, /disabled=""/);
  assert.match(html, /Keep off/);
  assert.match(source, /window.confirm/);
  assert.match(source, /role="alert"/);
});
test("blocked enable opens an explanation before any confirmation or mutation", () => {
  const guard = source.indexOf('if (action === "enable" && !item.can_enable)');
  assert.ok(guard >= 0 && guard < source.indexOf('window.confirm'));
  assert.match(source, /setBlocked\(item\); return/);
  assert.match(source, /Nothing was enabled/);
  assert.match(source, /onCancel=\{\(\) => setBlocked\(null\)\}/);
});
test("executable recommendations retain their explicit turn-on action", () => {
  const html = render([{...fixture, kind: "new_match", can_enable: true}]);
  assert.match(html, /Turn on · paper/);
  assert.doesNotMatch(html, /Why unavailable/);
});
