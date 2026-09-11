import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/settings/TestedStrategies.tsx", import.meta.url), "utf8");
const cardSource = readFileSync(new URL("../src/components/settings/StrategyToggleCard.tsx", import.meta.url), "utf8");
const apiStub = "data:text/javascript," + encodeURIComponent("export const api = {settings:{testedStrategies:()=>Promise.resolve({})}};");
let cardCompiled = ts.transpileModule(cardSource, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText;
cardCompiled = cardCompiled.replaceAll(JSON.stringify("react/jsx-runtime"), JSON.stringify(import.meta.resolve("react/jsx-runtime")));
const cardStub = `data:text/javascript;base64,${Buffer.from(cardCompiled).toString("base64")}`;
let compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText;
for (const name of ["react", "react/jsx-runtime", "@tanstack/react-query"]) {
  compiled = compiled.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name)));
}
compiled = compiled.replace('"../../lib/api"', JSON.stringify(apiStub));
compiled = compiled.replace('"./StrategyToggleCard"', JSON.stringify(cardStub));
compiled = compiled.replace('"./PairEvidence"', JSON.stringify('data:text/javascript,export function PairEvidence(){return null}'));
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
function render(data, researchIds = [], researchMatrix) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  if (data) client.setQueryData(["tested-strategies", researchIds], data);
  const html = renderToStaticMarkup(createElement(QueryClientProvider, {client},
    createElement(TestedStrategies, {researchIds, researchMatrix, onResearchIdsChange: () => {}})));
  client.clear();
  return html;
}

test("developer research archives are not shown as user controls", () => {
  const html = render(fixture);
  assert.doesNotMatch(html, /Saved research archive|VWAP pullback|Legacy test|Saved test only/);
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

test("working research strategies use the same accessible toggle-card pattern", () => {
  const runtime = [{
    strategy_id: "V2_OPENING_MOMENTUM_RTH_EXPLORATORY",
    display_name: "Opening Momentum", version: "research.1",
    exit_minutes: 90, enabled: true, research_scope: "all_collected_tickers",
  }];
  const html = render({...fixture, runtime_research: runtime}, [runtime[0].strategy_id]);
  assert.match(html, /Opening Momentum/);
  assert.match(html, /role="switch"/);
  assert.match(html, /aria-checked="true"/);
  assert.match(html, /Strategy-exit PF/);
  assert.match(html, /0 completed tests/);
  assert.doesNotMatch(html, /Research only · Testing every collected ticker/);
  assert.doesNotMatch(html, /research\.1/);
  assert.doesNotMatch(html, /type="checkbox"/);
});

test("settings headline uses the shared actual strategy-exit evidence", () => {
  const strategy_id = "V2_IMPULSE_ANCHORED_VWAP_PULLBACK";
  const data = {...fixture, runtime_research: [{strategy_id, display_name: "Impulse Anchored VWAP"}]};
  const html = render(data, [strategy_id], {strategies: [{
    strategy_id, exit_measurement: {pf_label: "Strategy-exit PF"},
    current_evidence: {profit_factor: 0.5, option_results: 2},
  }]});
  assert.match(html, /Strategy-exit PF 0.50/);
  assert.match(html, /2 completed tests/);
  assert.doesNotMatch(html, /Current PF/);
});
