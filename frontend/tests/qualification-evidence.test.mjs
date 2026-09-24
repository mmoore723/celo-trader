import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const source = readFileSync(new URL('../src/components/research/QualificationEvidence.tsx', import.meta.url), 'utf8');
let code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext } }).outputText;
code = code.replaceAll('"react/jsx-runtime"', JSON.stringify(import.meta.resolve('react/jsx-runtime')))
  .replaceAll('"../../lib/researchPairView.js"', JSON.stringify(new URL('../src/lib/researchPairView.js', import.meta.url).href));
const { QualificationEvidence } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const evidence = { qualified:false, independent_trades:51, remaining_trades:0,
  training:{profit_factor:1.2}, validation:{profit_factor:1.48},
  reasons:['Latest 6 tests need PF 1.5 or higher', 'The typical test must finish with a profit after costs'] };
const render = value => renderToStaticMarkup(createElement(QualificationEvidence, {evidence:value}));

test('sufficient sample never implies qualification and all blockers are visible', () => {
  const html = render(evidence);
  assert.match(html, /51 independent tests/);
  assert.match(html, /Sample requirement met/);
  for (const reason of evidence.reasons) assert.ok(html.includes(reason));
  assert.doesNotMatch(html, /Research checks passed/);
  assert.match(html, /not the all-results PF above/);
});
test('insufficient sample shows remaining count', () => {
  assert.match(render({...evidence, independent_trades:15, remaining_trades:5}), /5 more needed/);
});
test('qualified research is not trading permission', () => {
  assert.match(render({...evidence,qualified:true,reasons:[]}), /Trading approval is separate in Settings/);
});
test('missing evidence never claims a pass', () => {
  assert.match(render(undefined), /Qualification data unavailable/);
  assert.doesNotMatch(render(undefined), /checks passed/);
});
