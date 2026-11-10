const { chromium } = await import(process.env.CELO_PLAYWRIGHT_MODULE || 'playwright');
import assert from 'node:assert/strict';
const browser = await chromium.launch({headless:true,channel:'chrome'});
try {
  const page = await browser.newPage({viewport:{width:390,height:850}});
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:5174/tests/admin-activity.fixture.html');
  await page.getByText('SPY capture received',{exact:false}).waitFor();
  await page.getByLabel('Warnings and errors').check();
  assert.equal(await page.getByText('SPY capture received',{exact:false}).count(),0);
  await page.getByLabel('Warnings and errors').uncheck();
  await page.getByRole('button',{name:'Pause log',exact:true}).click();
  await page.getByRole('button',{name:'Add fixture event'}).click();
  assert.equal(await page.getByText('New event',{exact:false}).count(),0);
  await page.getByRole('button',{name:'Resume log',exact:true}).click();
  await page.getByText('New event',{exact:false}).waitFor();
  await page.getByLabel('Search activity').fill('QQQ');
  assert.equal(await page.getByLabel('Recent activity events').locator('li').count(),1);
  await page.getByRole('button',{name:'Disconnect fixture'}).click();
  await page.getByText('Activity feed disconnected.',{exact:false}).waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  assert.deepEqual(errors,[]);
  console.log('PASS: activity filter, warnings, pause/resume, disconnect and mobile width. Mocked events only.');
} finally { await browser.close(); }
