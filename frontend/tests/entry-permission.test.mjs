import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const sidebar=readFileSync(new URL('../src/components/layout/Sidebar.tsx',import.meta.url),'utf8');
const admin=readFileSync(new URL('../src/pages/Admin.tsx',import.meta.url),'utf8');
const activity=readFileSync(new URL('../src/components/AdminActivityLog.tsx',import.meta.url),'utf8');
test('entry permission has explicit all-entry controls and displays mode separately',()=>{
  assert.match(sidebar,/Pause all entries/); assert.match(sidebar,/Resume all entries/);
  assert.match(sidebar,/Paper mode/); assert.match(sidebar,/setControlMessage\(result.message\)/);
  assert.match(sidebar,/entryPermission.refetch/);
});
test('admin log is admin-gated and uses existing read-only store',()=>{
  assert.match(admin,/user\?\.is_admin && <AdminActivityLog/);
  assert.match(activity,/useBotStore/);
  assert.doesNotMatch(activity,/fetch\(|api\.|new WebSocket/);
  assert.match(activity,/Activity feed disconnected/);
});
