const {chromium}=await import(process.env.CELO_PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true,channel:'chrome'});
try {
  const page=await browser.newPage({viewport:{width:1500,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',route=>route.fulfill({json:route.request().url().includes('/signals/') ? {entries:[]} : []}));
  await page.goto('http://127.0.0.1:5174/tests/live-layout.fixture.html');
  const chart=page.getByTestId('live-chart-panel');
  const details=page.getByRole('complementary',{name:'Trading activity beside chart'});
  await details.waitFor();
  assert.equal(await page.getByLabel('Trading account snapshot').count(),1);
  assert.equal(await page.getByText('Trading workspace',{exact:true}).count(),0);
  const header=page.getByRole('banner');
  for(const label of ['Equity','Day Open','Today','Buying power','Open positions','$19,859.90','$16,219.90']) assert.equal(await header.getByText(label,{exact:true}).count(),1);
  for(const label of ['Setups and recent trades','Open Positions (0)','Live activity','Market Context']) {
    assert.equal(await details.getByText(label,{exact:true}).count(),1);
  }
  const c=await chart.boundingBox(),d=await details.boundingBox();
  assert.ok(d.x>=c.x+c.width && Math.abs(c.y-d.y)<2,'Details must sit to right of chart');
  await page.screenshot({path:'/tmp/celo-live-right-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:850});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'No page-wide horizontal overflow');
  const cm=await chart.boundingBox(),dm=await details.boundingBox();
  assert.ok(dm.y>=cm.y+cm.height,'Mobile must stack');
  await page.screenshot({path:'/tmp/celo-live-right-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: all four sections right of chart on desktop, stacked on mobile, no page errors. Mocked empty data.');
} finally {await browser.close();}
