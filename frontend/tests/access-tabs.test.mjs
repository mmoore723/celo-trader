import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source=readFileSync(new URL('../src/lib/access.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {limitedAccess,visibleTab}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
test('tiers filter tabs without granting order/admin access',()=>{
 for(const tier of ['watch','learning','learning_discord']){const u={access_profile:tier,is_admin:false};assert.equal(limitedAccess(u),true);assert.equal(visibleTab('/trading',u),true);for(const path of ['/admin','/settings','/performance','/journal'])assert.equal(visibleTab(path,u),false);assert.equal(visibleTab('/playbooks',u),tier!=='watch');}
 for(const tier of ['legacy','trading']){const u={access_profile:tier,is_admin:false};assert.equal(limitedAccess(u),false);assert.equal(visibleTab('/settings',u),true);assert.equal(visibleTab('/admin',u),false);}
 assert.equal(visibleTab('/admin',{is_admin:true,access_profile:'watch'}),true);
});
