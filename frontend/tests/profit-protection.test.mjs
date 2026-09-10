import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
const source=readFileSync(new URL("../src/components/ProfitProtectionComparison.tsx",import.meta.url),"utf8");
let code=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
code=code.replaceAll(JSON.stringify("react/jsx-runtime"),JSON.stringify(import.meta.resolve("react/jsx-runtime")))
  .replace(JSON.stringify("../lib/researchPairView.js"),JSON.stringify(new URL("../src/lib/researchPairView.js",import.meta.url).href));
const {ProfitProtectionComparison}=await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const render=comparison=>renderToStaticMarkup(createElement(ProfitProtectionComparison,{comparison}));
const empty={paired_results:0,paired_days:0,tracked:2,unpaired:2,statuses:{missing_path:1,missing_quote:1}};
test("unpriced tests are visible, not profitable or zero dollar results",()=>{
  const html=render(empty);
  assert.match(html,/No matched results yet/);
  assert.match(html,/1 incomplete price paths/);
  assert.match(html,/1 missing exit prices/);
  assert.doesNotMatch(html,/\$0.00|Option trail PF|Actual exit/);
  assert.equal(render(null),"");
});
test("comparison shows after-cost paired evidence without changing trading",()=>{
  const html=render({...empty,paired_results:2,paired_days:1,unpaired:0,
    control:{profit_factor:.8,net_pnl:-10},trail:{profit_factor:1.6,net_pnl:20},
    average_improvement:15,median_improvement:15});
  assert.match(html,/30-minute exit PF 0.80/);
  assert.match(html,/Option trail PF 1.60/);
  assert.match(html,/Average change \$15.00/);
  assert.match(html,/trading rules stay unchanged/);
  assert.match(html,/not broker fills/);
});
