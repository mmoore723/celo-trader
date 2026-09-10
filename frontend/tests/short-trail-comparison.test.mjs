import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/ShortTrailComparison.tsx", import.meta.url), "utf8");
let compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText;
compiled = compiled.replace('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")));
compiled = compiled.replace('"../lib/researchPairView.js"', JSON.stringify(new URL("../src/lib/researchPairView.js", import.meta.url).href));
const { ShortTrailComparison } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const render = comparison => renderToStaticMarkup(createElement(ShortTrailComparison, {comparison}));
const empty = {tracked: 2, paired_results: 0, paired_days: 0, unpaired: 2,
  original: {}, corrected: {}, average_improvement: null, median_improvement: null};

test("unpaired option prices never look like successful comparison results", () => {
  assert.equal(render(undefined), "");
  const html = render(empty);
  assert.match(html, /No matched results yet/);
  assert.match(html, /2 of 2 tests not yet comparable/);
  assert.doesNotMatch(html, /Original PF|Corrected PF|Average change/);
});

test("same-play results display negative change honestly and remain research only", () => {
  const html = render({...empty, paired_results: 1, paired_days: 1, unpaired: 1,
    original: {profit_factor: "infinite", net_pnl: 50, maximum_drawdown: 0},
    corrected: {profit_factor: 0, net_pnl: -20, maximum_drawdown: 20},
    average_improvement: -70, median_improvement: -70});
  assert.match(html, /Original PF No losses yet/);
  assert.match(html, /Corrected PF 0.00/);
  assert.match(html, /Average change \$-70.00/);
  assert.match(html, /Research only/);
  assert.match(html, /No trading rules changed/);
});
