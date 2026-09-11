import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
const source = readFileSync(new URL("../src/components/ExpirationStudy.tsx", import.meta.url), "utf8");
let code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext } }).outputText;
code = code.replaceAll(JSON.stringify("react/jsx-runtime"), JSON.stringify(import.meta.resolve("react/jsx-runtime")))
  .replace(JSON.stringify("../lib/researchPairView.js"), JSON.stringify(new URL("../src/lib/researchPairView.js", import.meta.url).href));
const { ExpirationStudy } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const metrics = { option_results: 0, profit_factor: null, net_one_contract_pnl: null, average_one_contract_pnl: null, median_one_contract_pnl: null, maximum_drawdown_one_contract: null };
const comparison = { results: 0, primary: metrics, longer: metrics, improved: 0, worsened: 0, unchanged: 0, average_change: null, median_change: null };
const empty = { setups: 3, selected_contracts: 2, first_setup_at: "2026-09-11T10:00:01", statuses: { no_contract: 1, missing_quote: 1 }, non_overlapping: metrics, matched: comparison, matched_non_overlapping: comparison, longer_only: metrics, primary_incomplete: 1 };
const render = study => renderToStaticMarkup(createElement(ExpirationStudy, { study }));
test("study stays collapsed, dated and does not show missing profit as zero", () => {
  const html = render(empty);
  assert.match(html, /Started Sep 11, 2026/);
  assert.match(html, /No completed same-setup comparison yet/);
  assert.match(html, /1 missing usable exit data/);
  assert.match(html, /Does not change the main PF/);
  assert.doesNotMatch(html, /\$0.00|<details open|<button/);
  assert.equal(render(null), "");
});
test("matched outcomes are separate from longer-only availability", () => {
  const priced = { ...metrics, option_results: 1, profit_factor: "infinite", net_one_contract_pnl: 10, median_one_contract_pnl: 10 };
  const html = render({ ...empty, matched: { ...comparison, results: 1, primary: { ...priced, profit_factor: 0, net_one_contract_pnl: -5 }, longer: priced, improved: 1, average_change: 15 }, longer_only: priced });
  assert.match(html, /Same setups/);
  assert.match(html, /Average change \$15.00/);
  assert.match(html, /These are not matched improvements/);
  assert.match(html, /No losses yet/);
  assert.match(html, /scope="col"/);
  assert.match(html, /scope="row"/);
});
