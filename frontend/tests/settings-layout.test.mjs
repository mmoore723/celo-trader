import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";

const source = readFileSync(new URL('../src/pages/Settings.tsx', import.meta.url), 'utf8');
const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');

test('Settings uses available page width and one/two/three content-width columns', () => {
  assert.doesNotMatch(source, /max-w-(2xl|5xl)/);
  assert.match(css, /\.settings-page[^}]*container-type: inline-size/);
  assert.match(css, /@container \(min-width: 48rem\)[\s\S]*?repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(css, /@container \(min-width: 78rem\)[\s\S]*?repeat\(3, minmax\(0, 1fr\)\)/);
  assert.match(css, /grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(css, /\.app-shell[^}]*grid-template-columns: var\(--sidebar-w\) minmax\(0, 1fr\)/);
  assert.match(css, /@media \(max-width: 767px\)[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(css, /\.settings-wide \{ grid-column: 1 \/ -1;/);
});

test('Both tabs retain accessible panels and independent credential saves', () => {
  assert.match(source, /hidden=\{activeTab !== "general"\}[^\n]*flex flex-col gap-4/);
  assert.match(source, /hidden=\{activeTab !== "strategies"\}[^\n]*role="tabpanel"/);
  assert.match(source, /<TestedStrategies\s+embedded/);
  assert.match(source, /settings-paired-grid[\s\S]*<AlpacaCredentialsPanel \/>[\s\S]*<TradierCredentialsPanel/);
  assert.doesNotMatch(css, /grid-auto-flow:\s*dense/);
});

test('General groups related controls into two independent vertical stacks', () => {
  const general=source.slice(source.indexOf('id="settings-panel-general"'),source.indexOf('id="settings-panel-strategies"'));
  assert.match(general, /settings-paired-grid settings-general-columns/);
  assert.equal((general.match(/settings-control-stack/g) ?? []).length, 2);
  const preferences=general.slice(general.indexOf('aria-label="Trading preferences"'),general.indexOf('aria-label="Trade rules and scanner"'));
  assert.match(preferences,/Trading mode[\s\S]*Display/);
  assert.doesNotMatch(preferences,/Trade limits|Always include/);
  const rules=general.slice(general.indexOf('aria-label="Trade rules and scanner"'),general.indexOf('aria-label="API credentials"'));
  assert.match(rules,/Trade limits[\s\S]*Entry and exit controls[\s\S]*Always include/);
  assert.doesNotMatch(general,/settings-card-grid/);
  assert.match(css,/\.settings-control-stack[^}]*display: flex;[^}]*flex-direction: column/);
});
