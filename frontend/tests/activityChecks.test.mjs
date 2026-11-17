import test from 'node:test';
import assert from 'node:assert/strict';
import { activityChecks } from '../src/lib/activityChecks.js';
test('recorded status and boolean checks retain their colors', () => {
  assert.deepEqual(activityChecks({checks:[{name:'VWAP',status:'passed'},
    {name:'Touch',state:'priming'}, {name:'Close',passed:false}]}).map(x=>x.state),
    ['passed','pending','failed']);
});
test('empty conditions does not hide checks and prose never implies readiness', () => {
  assert.equal(activityChecks({conditions:[],checks:[{label:'VWAP',passed:true}]})[0].state,'passed');
  assert.deepEqual(activityChecks({message:'All checks passed'}),[]);
  assert.equal(activityChecks({checks:[{name:'VWAP',status:'unchecked'}]})[0].state,'unknown');
});
