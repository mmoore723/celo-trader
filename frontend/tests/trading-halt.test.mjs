import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/TradingHaltBanner.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText
  .replace('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")))
  .replace('"react"', JSON.stringify(import.meta.resolve("react")))
  .replace('import { useTradingHalt } from "../hooks/useTradingHalt";', 'const useTradingHalt = () => globalThis.__haltFixture;')
  .replace('import.meta.env.VITE_API_URL', 'undefined');
const { TradingHaltBanner } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
function render(data, isError = false) {
  globalThis.__haltFixture = { data, isError };
  return renderToStaticMarkup(createElement(TradingHaltBanner));
}
test("halt presents explicit resume and keep halted controls", () => {
  const html = render({ halted: true, reason: "Daily loss cap", close_pending: false });
  assert.match(html, /TRADING HALTED/);
  assert.match(html, /Daily loss cap/);
  assert.match(html, /Keep halted/);
  assert.match(html, /Resume trading/);
  assert.doesNotMatch(html, /disabled=""/);
});
test("pending broker exits disable resume", () => {
  assert.match(render({ halted: true, close_pending: true }), /disabled=""/);
});
test("failed status refresh stays visible and disables resume", () => {
  const html = render({ halted: false }, true);
  assert.match(html, /TRADING STATUS UNVERIFIED/);
  assert.match(html, /disabled=""/);
});
test("no loss halt produces no warning", () => {
  assert.equal(render({ halted: false }), "");
});
test("halt banners live inside the scrollable main area, not implicit sidebar grid cells", () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /<main className="app-main"[^>]*>\s*<div className="app-alerts">\s*<BrokerAlertBanner \/>\s*<TradingHaltBanner \/>/);
  assert.match(source, /result.ok === true/);
  assert.match(source, /Still halted:/);
  assert.match(source, /result.detail/);
});
