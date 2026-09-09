// Run against a local Vite server, e.g. CELO_CHART_TEST_URL=http://127.0.0.1:5174
import { chromium } from "playwright";
import assert from "node:assert/strict";

const browser = await chromium.launch({ headless: true, channel: process.env.CELO_TEST_BROWSER ?? "chrome" });
const page = await browser.newPage({ viewport: { width: 1100, height: 950 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const now = Math.floor(Date.now()/1000);
let state = "normal";
await page.route("**/api/**", async route => {
  if (route.request().url().includes("/auth/me")) return route.fulfill({ json: { user_id: "fixture", username: "fixture", terms_accepted: true } });
  if (state === "error") return route.fulfill({ status: 503, json: { detail: "offline fixture" } });
  const tsla = route.request().url().includes("/2/option-chart");
  const entry = tsla ? 1.8 : 4.13;
  await route.fulfill({ json: {
    trade_id: tsla ? 2 : 1, ticker: tsla ? "TSLA" : "SPY", mode: "paper",
    contract_symbol: "FIXTURE_ONLY", option_type: tsla ? "put" : "call", strike: tsla ? 350 : 770,
    expiry: "2026-09-04", contracts: tsla ? 1 : 2, entry_price: entry, entry_time: now-1800,
    stop_price: tsla ? 1.2 : 3.3, target_price: tsla ? 3 : 6.2, exit_price: null,
    exit_time: null, realized_pnl: null, closed: false, truncated: false, as_of: now,
    candle_source: state === "empty" ? null : "tradier_timesales_1min",
    candles: state === "empty" ? [] : Array.from({ length: 30 }, (_, i) => {
      const close = entry+Math.sin(i/4)*0.25+i*0.015;
      const open = entry+Math.sin(Math.max(0, i-1)/4)*0.25+Math.max(0, i-1)*0.015;
      return { time: now-1800+i*60, open, high: Math.max(open, close)+0.06,
        low: Math.max(0.01, Math.min(open, close)-0.05), close, volume: 20+i*3 };
    }),
    quotes: state === "empty" ? [] : Array.from({ length: 30 }, (_, i) => ({ time: now-1800+i*60-(state === "stale" ? 900 : 0), bid: entry+Math.sin(i/4)*0.25+i*0.015, ask: entry+Math.sin(i/4)*0.25+i*0.015+0.06 })),
  } });
});
try {
  await page.goto(`${process.env.CELO_CHART_TEST_URL ?? "http://127.0.0.1:5174"}/tests/option-chart.fixture.html`);
  await page.getByRole("button", { name: "Select SPY" }).click();
  await page.getByRole("heading", { name: "SPY 770 CALL · 2026-09-04" }).waitFor();
  assert.equal(await page.getByTestId("profit-zone").count(), 1);
  assert.equal(await page.getByTestId("risk-zone").count(), 1);
  assert.equal(await page.getByTestId("option-candle").count(), 30);
  await page.screenshot({ path: "/private/tmp/celo-option-chart-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "Stock price", exact: true }).click();
  await page.getByRole("button", { name: "Refresh state", exact: false }).click();
  await page.getByText("Stock chart preserved").waitFor();
  await page.getByRole("button", { name: "Select TSLA" }).click();
  await page.getByRole("heading", { name: "TSLA 350 PUT · 2026-09-04" }).waitFor();
  assert.equal(await page.getByRole("heading", { name: /SPY/ }).count(), 0);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  }
  await page.screenshot({ path: "/private/tmp/celo-option-chart-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Theme", exact: true }).click();
  await page.screenshot({ path: "/private/tmp/celo-option-chart-dark.png", fullPage: true });
  for (const scenario of ["stale", "empty", "error"]) {
    state = scenario;
    await page.getByRole("button", { name: "Stock price", exact: true }).click();
    await page.getByRole("button", { name: "Option price", exact: true }).click();
    await page.getByText(scenario === "stale" ? /not a current price/ : scenario === "empty" ? /No one-minute trades were returned/ : /Option prices could not be loaded/).waitFor();
  }
  state = "normal";
  await page.getByRole("button", { name: "Try again" }).click();
  await page.getByRole("heading", { name: /TSLA/ }).waitFor();
  assert.deepEqual(errors, []);
  console.log("PASS: real option candles, position selection, stock override survives refresh, call/put identity, risk boxes, 320/390px, dark theme, stale/empty/error/retry; no page errors.");
} finally { await browser.close(); }
