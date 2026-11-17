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

test('candle history waits are separate from entry conditions still priming', () => {
  const rows = activityChecks({checks:[
    {name:'Completed candles',status:'pending',reason:'17 available; need 20.'},
    {name:'Rejection close',status:'pending',reason:'Waiting for a candle close.'},
    {name:'Completed candles',passed:true},
    {name:'Completed candles',passed:false},
    {name:'Completed candles',status:'unknown'},
  ]});
  assert.deepEqual(rows.map(x=>x.state), ['waiting','pending','passed','failed','unknown']);
  assert.equal(rows[0].reason, '17 available; need 20.');
});
