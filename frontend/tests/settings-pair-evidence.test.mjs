import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { settingsPairEvidenceRows } from "../src/lib/settingsPairEvidence.js";

const source = readFileSync(new URL('../src/components/settings/PairEvidence.tsx', import.meta.url), 'utf8');
let compiled = ts.transpileModule(source, {compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
}}).outputText;
compiled = compiled.replaceAll(JSON.stringify('react/jsx-runtime'), JSON.stringify(import.meta.resolve('react/jsx-runtime')));
for (const file of ['researchPairView.js', 'settingsPairEvidence.js']) {
  compiled = compiled.replaceAll(JSON.stringify(`../../lib/${file}`), JSON.stringify(new URL(`../src/lib/${file}`, import.meta.url).href));
}
const { PairEvidence } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const pair = (ticker, extra={}) => ({ticker, option_results:20, profit_factor:1.54,
  net_one_contract_pnl:15, tradable:false, recommendation:{independent_trades:20,
    qualified:false, reasons:['The typical test must finish with a profit after costs']}, ...extra});

test('saved enabled tickers sort first, alphabetical within both groups, without mutating evidence', () => {
  const input = [pair('META'), pair('SPY'), pair('AAPL'), pair('QQQ'), pair('EMPTY',{option_results:0})];
  const copy = structuredClone(input);
  const rows = settingsPairEvidenceRows(input, ['SPY','QQQ']);
  assert.deepEqual(rows.map(r => r.pair.ticker), ['QQQ','SPY','AAPL','META']);
  assert.deepEqual(rows.map(r => r.trading), [true,true,false,false]);
  assert.deepEqual(input, copy);
});

test('fresh saved grants override a stale research tradable flag and include enabled tickers with no tests', () => {
  const rows = settingsPairEvidenceRows([pair('META',{tradable:true}),pair('SPY',{option_results:0})], ['SPY']);
  assert.deepEqual(rows.map(r => [r.pair.ticker,r.trading]), [['SPY',true],['META',false]]);
  assert.equal(settingsPairEvidenceRows([pair('META',{tradable:true})], [])[0].trading,false);
});

test('ticker rows use explicit status text and distinct color classes, not PF to imply trading', () => {
  const html = renderToStaticMarkup(createElement(PairEvidence, {strategy:{pairs:[pair('META'),pair('SPY')]}, tradingTickers:['SPY']}));
  assert.ok(html.indexOf('>SPY<') < html.indexOf('>META<'));
  assert.match(html, /strategy-scope-trading/);
  assert.match(html, /strategy-scope-research/);
  assert.match(html, />Trading on</);
  assert.match(html, />Research only</);
  assert.match(html, /role="region"[^>]*tabindex="0"/);
  assert.match(html, /typical test must finish with a profit after costs/);
});

test('all recommendation blockers remain visible and empty data is explicit', () => {
  const blocked = pair('META',{recommendation:{independent_trades:42, qualified:false, reasons:['First blocker','Second blocker']}});
  const html = renderToStaticMarkup(createElement(PairEvidence, {strategy:{pairs:[blocked]},tradingTickers:[]}));
  assert.match(html, /First blocker · Second blocker/);
  assert.match(renderToStaticMarkup(createElement(PairEvidence, {})), /No completed strategy-exit tests yet/);
});

test('status badge text contrast exceeds 4.5 in light and dark themes', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url),'utf8');
  const luminance = hex => {
    const values = hex.match(/\w\w/g).map(x => parseInt(x,16)/255).map(x => x<=.04045 ? x/12.92 : ((x+.055)/1.055)**2.4);
    return values[0]*.2126+values[1]*.7152+values[2]*.0722;
  };
  const matches = [...css.matchAll(/--scope-ink: #(\w{6}); --scope-bg: #(\w{6});/g)];
  assert.equal(matches.length,6);
  for (const [,ink,bg] of matches) {
    const a=luminance(ink), b=luminance(bg);
    assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,`${ink} on ${bg}`);
  }
});
