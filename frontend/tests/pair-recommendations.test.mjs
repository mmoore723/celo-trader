import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { resolveStrategyIdentity } from "./strategy-identity-loader.mjs";
const source = readFileSync(new URL("../src/components/settings/StrategyRecommendations.tsx", import.meta.url), "utf8");
let compiled = ts.transpileModule(source, {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext}}).outputText;
compiled = compiled.replace('import { request } from "../../lib/api";', 'const request = async () => { throw new Error("No API calls during static render"); };');
compiled = compiled.replace('import { ResearchPairControl } from "../research/ResearchPairControl";', 'const ResearchPairControl = () => null;');
let premium = ts.transpileModule(readFileSync(new URL('../src/components/research/PremiumExitEvidence.tsx', import.meta.url), 'utf8'), {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
premium = premium.replace(/import \{ request \} from ['"]..\/..\/lib\/api['"];?/, 'const request = async () => { throw new Error("No API calls during static render"); };');
premium = premium.replace(/import \{ useAuth \} from ['"]..\/..\/contexts\/AuthContext['"];?/, 'const useAuth = () => ({user: null});');
for (const name of ["react", "react/jsx-runtime"]) premium = premium.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name))).replaceAll("'" + name + "'", JSON.stringify(import.meta.resolve(name)));
compiled = compiled.replace("'../research/PremiumExitEvidence'", JSON.stringify('data:text/javascript;base64,' + Buffer.from(premium).toString('base64')));
const dates = ts.transpileModule(readFileSync(new URL('../src/lib/evidencePeriod.ts', import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const rules = ts.transpileModule(readFileSync(new URL('../src/lib/researchRuleText.ts', import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
compiled = compiled.replace('"../../lib/researchRuleText"', JSON.stringify('data:text/javascript;base64,' + Buffer.from(rules).toString('base64')));
compiled = compiled.replace('"../../lib/evidencePeriod"', JSON.stringify('data:text/javascript;base64,' + Buffer.from(dates).toString('base64')));
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
  assert.match(html, /Review activation/);
  assert.doesNotMatch(html, /Turn on ·/);
  assert.doesNotMatch(html, /disabled=""/);
  assert.match(html, /Keep off/);
  assert.match(source, /window.confirm/);
  assert.match(source, /role="alert"/);
});
test("blocked enable opens an explanation before any confirmation or mutation", () => {
  const guard = source.indexOf('if (action === "enable" && !item.can_enable)');
  assert.ok(guard >= 0 && guard < source.indexOf('window.confirm'));
  assert.match(source, /await openReview\(item\); return/);
  assert.match(source, /blockedReason=/);
  assert.match(source, /onCancel=/);
});
test("executable recommendations retain their explicit turn-on action", () => {
  const html = render([{...fixture, kind: "new_match", can_enable: true}]);
  assert.match(html, /Review activation/);
  assert.doesNotMatch(html, /Why unavailable/);
});
test('activation uses the shared research settings modal, not an approval queue', () => {
  assert.match(source, /<ResearchPairControl/);
  assert.match(source, /pair=\{review.research_pair\}/);
  assert.match(source, /Exact recorded parameters/);
  assert.doesNotMatch(source, /Save implementation approval|Which rules should be implemented|Coverage and missing data/);
});

test('Auto Review renders persisted eight-exit confidence and bucket selector', () => {
  const report = {bucket:'test', strategy_id:'V2_SPY_TREND_CONT', ticker:'SPY', strategy_version:'1', candidates:[{rule:'gain_2pct',label:'2% Premium Gain',paired_trades:0,sessions:0,coverage:0,baseline:{},candidate:{},confidence:.99375,tested_exits:8,status:'collecting',exclusions:{},historical:{paired_trades:0}}], baseline_source:'Recorded deployed exit', specification:'premium-exits-v2', execution_validation:null};
  const html = renderToStaticMarkup(createElement(StrategyRecommendations, {recommendations:[], premiumReviews:[report], onDecision:async()=>{}}));
  assert.match(html, /Profit-taking exit review/);
  assert.match(html, /<select/);
  assert.match(html, /Recorded deployed exit/);
  assert.match(html, /99.375/);
  assert.match(html, /8 exit tests/);
});
