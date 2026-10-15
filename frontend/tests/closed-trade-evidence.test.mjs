import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const source = readFileSync(new URL('../src/components/settings/ClosedTradeEvidence.tsx', import.meta.url), 'utf8');
let code = ts.transpileModule(source, {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext}}).outputText;
code = code.replaceAll(JSON.stringify('react/jsx-runtime'), JSON.stringify(import.meta.resolve('react/jsx-runtime')))
  .replace(JSON.stringify('../../lib/closedTradeView.js'), JSON.stringify(new URL('../src/lib/closedTradeView.js', import.meta.url).href));
const {ClosedTradeEvidence} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const pair = {ticker:'SPY', version:'2.1.0', completed_trades:4, profit_factor:0.43, realized_pnl:-40, wins:1,
  first_entry_date:'2026-09-08', last_exit_date:'2026-09-11',
  exclusions:{still_open:1, different_or_unknown_version:12, incomplete_record:2, missing_parent:1}};
function render(props = {}, row = pair) {
  return renderToStaticMarkup(createElement(ClosedTradeEvidence, {strategyId:'V2_SPY_TREND_CONT', failed:false, loading:false,
    data:{available:true, account_mode:'paper', strategies:[{strategy_id:'V2_SPY_TREND_CONT', version:'2.1.0', pairs:[row]}]}, ...props}));
}
test('trade details label counted dates and exclusions without changing headline results', () => {
  const html = render();
  for (const text of ['What’s included in these results?', 'PF 0.43', '4 closed trades', '2026-09-08 to 2026-09-11',
    '1 still open', '12 from other or unknown versions', '3 incomplete records', 'Not backtests.', 'Partial sells count as one trade when fully closed.']) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /Trade dates and counts|reconciliation|<details[^>]* open/);
});
test('empty and failed results do not invent date ranges or undefined versions', () => {
  const html = render({}, {...pair, completed_trades:0, first_entry_date:null, last_exit_date:null, exclusions:{}});
  assert.match(html, /No closed trades yet/);
  assert.doesNotMatch(html, /Not counted|undefined/);
  assert.match(render({failed:true}), /Trade results could not load/);
  assert.doesNotMatch(render({failed:true}), /What’s included/);
});
