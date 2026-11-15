import test from 'node:test';
import assert from 'node:assert/strict';
import {effectiveExecution} from '../src/lib/strategyConfiguration.js';
test('configuration matches timer and ranking precedence without mutating saved state',()=>{
 const defaults={contract:{primary_policy:'closest_otm_150_1000',minimum_dte:0},native_exit:{max_hold_bars:75}};
 const overrides={native_exit:{max_hold_bars:20}};
 const selected={exit_minutes:60,contract_policy:'highest_volume_150_1000'};
 const before=JSON.stringify({defaults,overrides,selected});
 let view=effectiveExecution(defaults,overrides,selected);
 assert.equal(view.native_exit.hold_minutes,60);
 assert.equal(view.contract.primary_policy,selected.contract_policy);
 assert.equal(view.native_exit.max_hold_bars,20);
 assert.equal(JSON.stringify({defaults,overrides,selected}),before);
 view=effectiveExecution(defaults,{native_exit:{hold_minutes:45}},selected);
 assert.equal(view.native_exit.hold_minutes,45);
 assert.deepEqual(effectiveExecution(defaults,overrides,selected,true).native_exit,{});
 assert.equal(effectiveExecution(defaults,{}, {...selected,exit_minutes:null}).native_exit.hold_minutes,undefined);
});
test('editing a contract filter keeps the selected ranking shown in the panel',()=>{
 const defaults={contract:{primary_policy:'closest_otm_150_1000',minimum_dte:0},native_exit:{}};
 const selected={exit_minutes:null,contract_policy:'highest_volume_150_1000'};
 const current=effectiveExecution(defaults,{},selected);
 const edited={contract:{...current.contract,minimum_dte:4}};
 assert.equal(effectiveExecution(defaults,edited,selected).contract.primary_policy,'highest_volume_150_1000');
 assert.equal(effectiveExecution(defaults,edited,selected).contract.minimum_dte,4);
});
