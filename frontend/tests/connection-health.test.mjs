import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { connectionHealthView, needsTradierSandbox } from "../src/lib/connectionHealthView.js";

const now = Date.parse("2026-09-03T18:31:00Z");
const health = {
  ready: true, mode: "paper", selected_broker: "alpaca", checked_at: "2026-09-03T18:30:45Z",
  connections: [
    { id: "alpaca", label: "Alpaca Paper", purpose: "Simulated orders", status: "connected", required: true },
    { id: "tradier", label: "Tradier Production", purpose: "Current prices", status: "connected", required: true },
    { id: "sandbox", label: "Tradier Sandbox", status: "not_used", required: false },
  ],
};

// Render the actual TSX component using the project's existing TS compiler.
const source = readFileSync(new URL("../src/components/ConnectionStatus.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText
  .replace('"react/jsx-runtime"', JSON.stringify(import.meta.resolve("react/jsx-runtime")))
  .replace('"../lib/connectionHealthView.js"', JSON.stringify(new URL("../src/lib/connectionHealthView.js", import.meta.url).href));
const { ConnectionStatus } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const render = (overrides = {}) => renderToStaticMarkup(createElement(ConnectionStatus, {
  health, now, checking: false, failed: false, onRefresh() {}, ...overrides,
}));

test("fresh connections show checked time and exclude unused sandbox", () => {
  const html = render();
  assert.match(html, /Alpaca Paper/);
  assert.match(html, /Tradier Production/);
  assert.match(html, /Connected/);
  assert.match(html, /2:30:45 PM.*ET/);
  assert.doesNotMatch(html, /Sandbox/);
  assert.equal(connectionHealthView(health, { now }).hasIssue, false);
});

test("failed refresh never presents cached connected status as current", () => {
  assert.doesNotMatch(render({ failed: true }), /Connected/);
  assert.match(render({ failed: true }), /Current status unavailable/);
  assert.match(render({ failed: true }), /Previous check/);
});

test("stale, malformed and future checks cannot appear connected", () => {
  for (const checked_at of ["2026-09-03T18:28:59Z", "invalid", "2026-09-03T18:40:00Z"]) {
    assert.doesNotMatch(render({ health: { ...health, checked_at } }), /Connected/);
  }
  assert.match(render({ health: undefined, checking: true }), /Checking current connections/);
});

test("current failure remains visible and is not hidden with unused rows", () => {
  const broken = { ...health, ready: false, connections: [
    { id: "tradier", label: "Tradier Production", status: "error", detail: "Authentication failed", required: true },
  ] };
  assert.equal(connectionHealthView(broken, { now }).hasIssue, true);
  assert.match(render({ health: broken }), /Authentication failed/);
});

test("sandbox controls only apply to the Tradier paper route", () => {
  assert.equal(needsTradierSandbox("alpaca", true), false);
  assert.equal(needsTradierSandbox("alpaca", false), false);
  assert.equal(needsTradierSandbox("tradier", false), false);
  assert.equal(needsTradierSandbox("tradier", true), true);
});
