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
const links = ts.transpileModule(readFileSync(new URL('../src/lib/learningLinks.ts', import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
code = code.replace("'../../lib/learningLinks'", JSON.stringify(`data:text/javascript;base64,${Buffer.from(links).toString('base64')}`));
code = code.replace("'../../lib/strategyIdentity.js'", JSON.stringify(new URL('../src/lib/strategyIdentity.js', import.meta.url).href));
const { TradingOverview } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const strategy = {strategy_id:'test',display_name:'Test strategy',version:'v1',trading_tickers:['SPY'],integrity_errors:[]};
const evidence = {available:true, account_mode:'paper', strategies:[{strategy_id:'test',version:'v1',pairs:[{ticker:'SPY',version:'v1',completed_trades:4,wins:3,realized_pnl:120,profit_factor:2,first_entry_date:'2026-10-01',last_exit_date:'2026-10-30'}]}]};
const render = (props={}) => renderToStaticMarkup(createElement(MemoryRouter,{},createElement(TradingOverview,{strategies:[strategy],evidence,mode:'paper',loading:false,failed:false,controls:()=>null,...props})));
test('learning links preserve the exact strategy ticker and version',()=>{
 const html=render();
 for(const view of ['lesson','reference','practice']) assert.ok(html.includes(`strategy=test&amp;ticker=SPY&amp;version=v1&amp;view=${view}`));
});
test('overview presents isolated actual metrics and two descriptive charts',()=>{
 const html=render();
 for(const text of ['$120.00','75.0%','2.00','Realized P&amp;L by pair','Wins versus other closed trades','v1','Journal results only']) assert.ok(html.includes(text),text);
 assert.doesNotMatch(html,/<details open/);
});
test('version, mode, errors and zero trades never become winning evidence',()=>{
 for(const props of [{strategies:[{...strategy,version:'v2'}]},{mode:'live'},{failed:true},{evidence:{...evidence,available:false}}]){
   const html=render(props); assert.doesNotMatch(html,/\$120.00|75.0%/);
 }
 assert.match(render({strategies:[]}),/No enabled trading pairs/);
});
