import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = readFileSync(new URL("../src/components/settings/StrategyExitNotice.tsx", import.meta.url), "utf8");
let compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext,
} }).outputText;
compiled = compiled.replaceAll(JSON.stringify("react/jsx-runtime"), JSON.stringify(import.meta.resolve("react/jsx-runtime")));
const { StrategyExitNotice } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("exit rules are explanatory, not a switch or input", () => {
  const html = renderToStaticMarkup(createElement(StrategyExitNotice));
  assert.match(html, /Strategy exit rules/);
  assert.match(html, /tested version/);
  assert.match(html, /account risk and daily loss/);
  assert.doesNotMatch(html, /<input|<button|role="switch"|<select/);
});

test("Settings cannot switch the exit engine or promise it controls reviewed exits", () => {
  const page = readFileSync(new URL("../src/pages/Settings.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(page, /set\("simplified_exit_mode"/);
  assert.doesNotMatch(page, /Simplified Exit is active|Only one exit engine ever runs|beat the full 9-condition/);
  assert.match(page, /<StrategyExitNotice/);
  assert.match(page, /set\("risk_pct"/);
  assert.match(page, /set\("daily_loss_hard_cap_pct"/);
});
