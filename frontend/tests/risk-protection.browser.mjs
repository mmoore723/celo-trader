const { chromium } = await import(process.env.CELO_PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';

const browser = await chromium.launch({headless:true,channel:'chrome'});
const page = await browser.newPage({viewport:{width:1100,height:950}});
const errors=[]; page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
  if(route.request().url().includes('/auth/me')) return route.fulfill({json:{user_id:'fixture',username:'fixture',terms_accepted:true}});
  const now=Date.now()/1000;
  return route.fulfill({json:{trade_id:1,ticker:'SPY',mode:'paper',contract_symbol:'FIXTURE',option_type:'call',strike:770,
    expiry:'2026-12-18',contracts:1,entry_price:4,entry_time:now-600,stop_price:3,target_price:6,
    exit_price:null,exit_time:null,realized_pnl:null,closed:false,truncated:false,as_of:now,
    candles:[],quotes:[{time:now,bid:4.1,ask:4.2}],candle_source:null,
    risk_classification:{observed_at:new Date().toISOString(),sizing_basis:'Full debit plus fees',levels:[
      {name:'option_stop',value:3,state:'Reference-only',reason:'Not an exit trigger.'},
      {name:'underlying_stop',value:760,state:'Enforced',reason:'Selected execution monitors this level.'},
      {name:'resistance',value:null,state:'Unavailable',reason:'No recorded level.'}]}}});
});
try {
  await page.goto('http://127.0.0.1:5174/tests/option-chart.fixture.html');
  await page.getByRole('button',{name:'Select SPY'}).click();
  await page.getByText('Inspect risk levels',{exact:true}).click();
  const panel=page.getByLabel('Protection status');
  await panel.getByText('Reference-only',{exact:true}).waitFor();
  assert.equal(await panel.getByText('Enforced',{exact:true}).count(),1);
  assert.equal(await panel.getByText('Unavailable',{exact:true}).count(),1);
  await page.screenshot({path:'/tmp/celo-risk-states-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:900});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:'/tmp/celo-risk-states-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: all three states visible, expandable detail, 390px no overflow, no browser errors. Mocked data only.');
} finally { await browser.close(); }
