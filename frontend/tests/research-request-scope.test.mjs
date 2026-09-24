import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

test('the large decisions feed is enabled only in the decisions view', () => {
  const source = readFileSync(new URL('../src/pages/ScannerOpportunities.tsx', import.meta.url), 'utf8');
  const file = ts.createSourceFile('ScannerOpportunities.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let options;
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(file) === 'useQuery' &&
        node.arguments[0]?.getText(file).includes('["scanner-opportunities", date]')) options = node.arguments[0];
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(options);
  const enabled = options.properties.find(prop => prop.name?.getText(file) === 'enabled');
  assert.ok(enabled, 'research must not fetch an unused 1,000-row decisions payload');
  assert.equal(enabled.initializer.getText(file), 'view === "decisions"');
});
