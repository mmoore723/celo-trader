import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
const errors=[];const requests=[];let fail=false;
page.on('pageerror',e=>errors.push(e.message));
const bar=(day,minute)=>({time:`2026-11-${day}T09:${minute}:00`,open:100,high:102,low:99,close:101,volume:100,vwap:100});
await page.route('**/api/**',async route=>{
 const url=new URL(route.request().url()); requests.push(url.pathname+url.search);
 if(url.pathname.includes('/auth/me'))return route.fulfill({json:{user_id:'fixture',username:'fixture',terms_accepted:true}});
 if(url.pathname.includes('/archived-bars/'))return fail?route.fulfill({status:503,json:{detail:'fixture unavailable'}}):route.fulfill({json:{bars:[bar('16','30'),bar('16','31'),bar('17','30'),bar('17','32')],dates:['2026-11-13','2026-11-16','2026-11-17'],missing_dates:['2026-11-13'],gaps:[{start:'2026-11-17T09:31:00-05:00',end:'2026-11-17T09:32:00-05:00',minutes:1}],partial_buckets_omitted:0,recovered_minutes:1,note:'No candles are filled in.'}});
 if(url.pathname.includes('/bars/'))return route.fulfill({json:[bar('17','30'),bar('17','32')]});
 if(url.pathname.includes('board'))return route.fulfill({json:{tickers:[]}});
 if(url.pathname.includes('opportunities'))return route.fulfill({json:{entries:[]}});
 return route.fulfill({json:[]});
});
try{
 await page.goto(`${process.env.CELO_CHART_TEST_URL??'http://127.0.0.1:5174'}/tests/archived-chart.fixture.html`);
 if(await page.getByRole('button',{name:'Show chart',exact:true}).count()) await page.getByRole('button',{name:'Show chart',exact:true}).click();
 for(const range of ['5D','1M','3M']){
  await page.getByRole('button',{name:range,exact:true}).click();
  await page.getByText('Saved candles:',{exact:false}).waitFor();
  assert.ok(requests.some(x=>x.includes('archived-bars')&&x.includes(`period=${range}`)&&x.includes('timeframe=1Min')));
 }
 await page.getByText('Data coverage:',{exact:false}).click();
 await page.getByText('No saved bars: 2026-11-13').waitFor();
 await page.getByText('2026-11-17 09:31 to 09:32 ET: 1 minutes unavailable').waitFor();
 assert.ok(await page.locator('canvas').count()>0);
 await page.screenshot({path:'/tmp/celo-archived-chart.png',fullPage:true});
 fail=true;
 await page.getByRole('button',{name:'5m',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'Chart data could not be loaded'}).waitFor();
 assert.deepEqual(errors,[]);
 console.log('PASS: all three archived ranges requested at 1m, gap details displayed, chart rendered, failed requests reported, no browser errors.');
}finally{await browser.close();}
