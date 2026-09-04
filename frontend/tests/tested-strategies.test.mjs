import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/settings/TestedStrategies.tsx", import.meta.url), "utf8");
const apiStub = "data:text/javascript," + encodeURIComponent("export const api = {settings:{testedStrategies:()=>Promise.resolve({})}};");
let compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText;
for (const name of ["react", "react/jsx-runtime", "@tanstack/react-query"]) {
  compiled = compiled.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name)));
}
compiled = compiled.replace('"../../lib/api"', JSON.stringify(apiStub));
const { TestedStrategies } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const fixture = {
  runtime_research: [],
  strategies: [{strategy_id: "OLD_VWAP", display_name: "VWAP pullback", tickers: ["TSLA"], reports: ["reports/test.json"], report_count: 1}],
  other_studies: ["reports/legacy.json"], reports_scanned: 2,
  report_details: {
    "reports/test.json": {title: "Old VWAP test", purpose: "<script>not trusted</script>", decision: "reject", status: "invalid_or_superseded"},
    "reports/legacy.json": {title: "Legacy test", purpose: "No strategy ID", decision: "", status: "saved_study"},
  },
};
function render(data, currentIds = [], researchIds = []) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  if (data) client.setQueryData(["tested-strategies", researchIds], data);
  const html = renderToStaticMarkup(createElement(QueryClientProvider, {client},
    createElement(TestedStrategies, {currentIds, researchIds, onResearchIdsChange: () => {}})));
  client.clear();
  return html;
}

test("historical and ID-less tests remain visible without order switches", () => {
  const html = render(fixture);
  assert.match(html, /VWAP pullback/);
  assert.match(html, /Legacy test/);
  assert.match(html, /Result: reject/);
  assert.doesNotMatch(html, /role="switch"|Enable for/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("current-catalog history is retained instead of filtered out", () => {
  assert.match(render(fixture, ["OLD_VWAP"]), /Already active elsewhere/);
  assert.match(render(fixture, ["OLD_VWAP"]), /Old VWAP test/);
});

test("loading and failed library are not reported as zero tested strategies", () => {
  const pending = render();
  assert.match(pending, /Loading strategies/);
  assert.doesNotMatch(pending, /No saved tests/);
  const failed = render({...fixture, unavailable: true});
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Try again/);
  assert.doesNotMatch(failed, /No saved tests|VWAP pullback/);
});

test("long inventories use a bounded first view and search", () => {
  const strategies = Array.from({length: 45}, (_, i) => ({...fixture.strategies[0], strategy_id: `S_${i}`, display_name: `Strategy ${i}`}));
  const html = render({...fixture, strategies});
  assert.match(html, /Strategy 29/);
  assert.doesNotMatch(html, /Strategy 30/);
  assert.match(html, /Showing the first 30 matches/);
  assert.match(html, /Find a strategy/);
});
