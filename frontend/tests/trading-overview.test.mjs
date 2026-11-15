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
let configCode = ts.transpileModule(readFileSync(new URL('../src/components/settings/StrategyConfiguration.tsx', import.meta.url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
for(const name of ['react','react/jsx-runtime']) configCode=configCode.replaceAll(JSON.stringify(name),JSON.stringify(import.meta.resolve(name))).replaceAll(`'${name}'`,JSON.stringify(import.meta.resolve(name)));
configCode=configCode.replace("'../../lib/strategyConfiguration'",JSON.stringify(new URL('../src/lib/strategyConfiguration.js',import.meta.url).href));
configCode=configCode.replace("'../../lib/strategySettingHelp'",JSON.stringify(new URL('../src/lib/strategySettingHelp.js',import.meta.url).href));
code=code.replace("'./StrategyConfiguration'",JSON.stringify(`data:text/javascript;base64,${Buffer.from(configCode).toString('base64')}`));
const { TradingOverview } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const strategy = {strategy_id:'test',display_name:'Test strategy',version:'v1',trading_tickers:['SPY'],integrity_errors:[]};
const evidence = {available:true, account_mode:'paper', strategies:[{strategy_id:'test',version:'v1',pairs:[{ticker:'SPY',version:'v1',completed_trades:4,wins:3,realized_pnl:120,profit_factor:2,first_entry_date:'2026-10-01',last_exit_date:'2026-10-30'}]}]};
const render = (props={}) => renderToStaticMarkup(createElement(MemoryRouter,{},createElement(TradingOverview,{strategies:[strategy],evidence,mode:'paper',loading:false,failed:false,controls:()=>null,...props})));
test('settings keeps lessons reference and practice in the Learning Hub',()=>{
 assert.doesNotMatch(render(),/playbooks|Lesson|Reference|Practice|Learn Test/);
});
test('one settings entry per ticker with no duplicate management or research controls',()=>{
 const html=render();
 assert.match(html,/Your strategies/);assert.match(html,/SPY/);assert.match(html,/Settings/);
 assert.doesNotMatch(html,/Manage this strategy|Configure SPY|Ticker details|Journal results|\$120.00|Research/);
 assert.match(html,/aria-expanded="false"/);
 assert.match(render({strategies:[]}),/No strategies are available/);
});

test('SPY and QQQ are branches of one Trend Continuation strategy',()=>{
 const variants=[{...strategy,strategy_id:'V2_SPY_TREND_CONT',display_name:'SPY Trend Continuation'}, {...strategy,strategy_id:'RESEARCH_QQQ_TREND_V2',display_name:'QQQ Trend V2',trading_tickers:['QQQ']}];
 const html=render({strategies:variants});
 assert.equal((html.match(/aria-label="Trend Continuation strategy"/g)||[]).length,1);
 assert.match(html,/1 strategies/);
 assert.doesNotMatch(html,/<table|Selected pair performance|Realized P&amp;L by pair/);
 assert.match(html,/>SPY</); assert.match(html,/>QQQ</);
});

test('unassigned research strategies do not create empty Settings cards',()=>{
 const html=render({strategies:[{...strategy,tickers:[],trading_tickers:[]}]});
 assert.doesNotMatch(html,/aria-label="Test strategy strategy"/);
 assert.match(html,/No strategies are available/);
});
