import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync, writeFileSync, readdirSync} from 'node:fs';
import {createElement as h} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const source=readFileSync(new URL('../src/components/settings/StrategyToggleCard.tsx',import.meta.url),'utf8');
let code=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext}}).outputText;
code=code.replaceAll(JSON.stringify('react/jsx-runtime'),JSON.stringify(import.meta.resolve('react/jsx-runtime')));
const {StrategyToggleCard}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const labels={trading:'Trading enabled',research:'Research only',paused:'Auto-paused ticker(s)'};
const render=activity=>renderToStaticMarkup(h(StrategyToggleCard,{activity,label:'Trend Continuation',checked:true,onChange:()=>{}},
  h('p',{className:'text-xs mb-2'},'SPY · research.1'),
  h('details',null,h('summary',null,'Research results and test evidence'),h('p',null,'Expanded evidence'))));
test('full-card status follows execution activity, not the research switch',()=>{
 for(const [activity,label] of Object.entries(labels)){
  const html=render(activity);
  assert.ok(html.includes(`strategy-scope-${activity}`));
  assert.ok(html.includes(label));
  assert.ok(html.includes('role="switch"'));
  assert.ok(html.includes('aria-checked="true"'));
  assert.ok(!html.includes('<details open'));
 }
});
if(process.env.CELO_CARD_PREVIEW){
 const assets=new URL('../dist/assets/',import.meta.url);
 const css=readdirSync(assets).filter(n=>n.endsWith('.css')).map(n=>readFileSync(new URL(n,assets),'utf8')).join('\n');
 const cards=Object.keys(labels).map(render).join('');
 writeFileSync('/tmp/celo-card-preview.html',`<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style><body><main class="settings-page" style="padding:20px"><div id="settings-panel-strategies"><h1>Strategy cards: visual test</h1><section class="settings-card-grid">${cards}</section><section class="dark settings-card-grid" style="background:#0f172a;padding:12px;margin-top:20px">${cards}</section></div></main></body>`);
}
