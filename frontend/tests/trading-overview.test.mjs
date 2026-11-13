import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import ts from 'typescript';
const source = readFileSync(new URL('../src/components/settings/TradingOverview.tsx', import.meta.url), 'utf8');
let code = ts.transpileModule(source, {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
for (const name of ['react', 'react/jsx-runtime', 'react-router-dom']) code = code.replaceAll(JSON.stringify(name), JSON.stringify(import.meta.resolve(name))).replaceAll(`'${name}'`, JSON.stringify(import.meta.resolve(name)));
code = code.replace("'../../lib/strategyIdentity.js'", JSON.stringify(new URL('../src/lib/strategyIdentity.js', import.meta.url).href));
const { TradingOverview } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const strategy = {strategy_id:'test',display_name:'Test strategy',version:'v1',trading_tickers:['SPY'],integrity_errors:[]};
const evidence = {available:true, account_mode:'paper', strategies:[{strategy_id:'test',version:'v1',pairs:[{ticker:'SPY',version:'v1',completed_trades:4,wins:3,realized_pnl:120,profit_factor:2,first_entry_date:'2026-10-01',last_exit_date:'2026-10-30'}]}]};
const render = (props={}) => renderToStaticMarkup(createElement(MemoryRouter,{},createElement(TradingOverview,{strategies:[strategy],evidence,mode:'paper',loading:false,failed:false,controls:()=>null,...props})));
test('settings keeps lessons reference and practice in the Learning Hub',()=>{
 assert.doesNotMatch(render(),/playbooks|Lesson|Reference|Practice|Learn Test/);
});
test('overview presents strategy umbrellas and keeps metrics inside ticker details',()=>{
 const html=render();
 for(const text of ['$120.00','75.0%','2.00','Your strategies','Ticker details','Manage this strategy','v1','Journal results only']) assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/<details open/);
});
test('version, mode, errors and zero trades never become winning evidence',()=>{
 for(const props of [{strategies:[{...strategy,version:'v2'}]},{mode:'live'},{failed:true},{evidence:{...evidence,available:false}}]){
   const html=render(props); assert.doesNotMatch(html,/\$120.00|75.0%/);
 }
 assert.match(render({strategies:[]}),/No enabled trading pairs/);
});

test('SPY and QQQ are branches of one Trend Continuation strategy',()=>{
 const variants=[{...strategy,strategy_id:'V2_SPY_TREND_CONT',display_name:'SPY Trend Continuation'}, {...strategy,strategy_id:'RESEARCH_QQQ_TREND_V2',display_name:'QQQ Trend V2',trading_tickers:['QQQ']}];
 const html=render({strategies:variants});
 assert.equal((html.match(/aria-label="Trend Continuation strategy"/g)||[]).length,1);
 assert.match(html,/1 strategies/);assert.match(html,/Trading on SPY, QQQ/);
 assert.doesNotMatch(html,/<table|Selected pair performance|Realized P&amp;L by pair/);
 assert.match(html,/>SPY</); assert.match(html,/>QQQ</);
});
