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
const {ProfitProtectionComparison,ReferenceContractTest}=await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const render=comparison=>renderToStaticMarkup(createElement(ProfitProtectionComparison,{comparison}));
test("four exit arms stay compact and missing prices do not become zero profit",()=>{
  const arms=Object.fromEntries(['original','profit_trail','loss_only','loss_and_trail'].map(k=>[k,{profit_factor:null,net_pnl:null}]));
  const html=render({paired_results:0,paired_days:0,tracked:2,unpaired:2,statuses:{},
    initial_loss_comparison:{tracked:2,paired_results:0,unpaired:2,arms,statuses:{loss_only:{missing_quote:1}}}});
  for(const label of ['Compare four exits','Original','Profit trail','Loss limit','Loss limit + trail','Unusable']) assert.ok(html.includes(label));
  assert.match(html,/2 of 2 plays not yet matched/);
  assert.match(html,/not a guaranteed loss cap/);
  assert.match(html,/Your trading exits have not changed/);
  assert.doesNotMatch(html,/\$0.00|<details open/);
});
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
test("recovery trail explains its target gate without claiming an immediate sale",()=>{
  const html=render({...empty,protocol:"recovery_vwap_then_option_3spread_2spread_30m_v1",target_reached:1});
  assert.match(html,/Recovery profit protection test/);
  assert.match(html,/1 plays reached the recovery target/);
  assert.match(html,/reaching it does not sell the position/);
  assert.doesNotMatch(render(empty),/reached the recovery target/);
});
const reference={profile_version:"reviewed_contract_reference_v1",minutes:90,tracked:2,selected:1,
  first_test_at:"2026-09-10T10:00:00",option_results:0,result_days:0,
  control:{profit_factor:null,net_pnl:null},statuses:{no_contract:1,missing_quote:1},profit_protection:null};
const renderReference=t=>renderToStaticMarkup(createElement(ReferenceContractTest,{test:t}));
test("reference cohort is separate, compact, dated, and missing is not zero profit",()=>{
  const html=renderReference(reference);
  assert.match(html,/7–21-day option test/);assert.match(html,/Started Sep 10, 2026/);
  assert.match(html,/90-minute exit/);assert.match(html,/1 missing exit prices/);
  assert.match(html,/not your account limits/);assert.match(html,/Separate from 0–7-day results/);
  assert.doesNotMatch(html,/\$0.00|<details open/);assert.equal(renderReference(null),"");
});
test("reference exit comparison cannot be mislabeled as the generic cohort",()=>{
  const html=renderReference({...reference,minutes:30,profit_protection:empty});
  assert.match(html,/7–21-day options/);
  assert.doesNotMatch(html,/0–7-day options/);
});
test("ORB comparison labels its actual 90-minute control in both cohorts",()=>{
  const comparison={...empty,minutes:90,protocol:"orb_option_3spread_arm_2spread_trail_90m_v1",
    paired_results:1,control:{profit_factor:.8,net_pnl:-10},trail:{profit_factor:1.6,net_pnl:20},
    average_improvement:30,median_improvement:30};
  for(const html of [render(comparison),renderReference({...reference,profit_protection:comparison})]){
    assert.match(html,/90-minute exit PF/);assert.match(html,/Both exit by 90 minutes/);
    assert.doesNotMatch(html,/30-minute|by 30 minutes/);
    assert.match(html,/trading rules stay unchanged/);
  }
});
