import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/AuthoredExitEvidence.tsx", import.meta.url), "utf8");
let compiled = ts.transpileModule(source, {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext}}).outputText;
compiled = compiled.replaceAll(JSON.stringify("react/jsx-runtime"), JSON.stringify(import.meta.resolve("react/jsx-runtime")));
compiled = compiled.replace(JSON.stringify("../lib/researchPairView.js"), JSON.stringify(new URL("../src/lib/researchPairView.js", import.meta.url).href));
const {AuthoredExitEvidence} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const empty = {option_results: 0, option_result_days: 0, profit_factor: null, collecting: 0,
  pending_quote: 0, missing_quote: 0, unmeasurable: 0, reasons: {}};
const render = evidence => renderToStaticMarkup(createElement(AuthoredExitEvidence, {evidence}));

test("actual exit evidence does not turn missing prices into zero profits", () => {
  const html = render({...empty, collecting: 2, missing_quote: 1, unmeasurable: 1, reasons: {missing_bars: 1}});
  assert.match(html, /0 results/);
  assert.match(html, /2 open tests/);
  assert.match(html, /2 missing usable data/);
  assert.match(html, /Missing candles: 1/);
  assert.doesNotMatch(html, /After-cost|\$0.00/);
  assert.equal("", render(null));
});

test("actual exit evidence displays its own after-cost sample and PF", () => {
  const html = render({...empty, option_results: 2, option_result_days: 2, profit_factor: 1.6,
    average_one_contract_pnl: 12, median_one_contract_pnl: 12, net_one_contract_pnl: 24});
  assert.match(html, /Actual exit PF: 1.60/);
  assert.match(html, /2 results · 2 result days/);
  assert.match(html, /After-cost P&amp;L \$24.00/);
});
