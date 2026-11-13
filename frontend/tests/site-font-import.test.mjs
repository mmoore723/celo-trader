import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
test('site font import precedes chart font declaration so CSS does not drop it',async()=>{
 const css=await readFile(new URL('../src/index.css',import.meta.url),'utf8');
 assert.ok(css.indexOf('@import')>=0&&css.indexOf('@import')<css.indexOf('@font-face'));
 assert.match(css,/family=Inter/); assert.match(css,/family=JetBrains/);
});
