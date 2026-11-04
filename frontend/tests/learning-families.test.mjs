import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/lib/learningFamilies.ts',import.meta.url),'utf8');
const code = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {learningFamily} = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const family = id => learningFamily({strategy_id:id,display_name:id});
test('ORB ticker and context variants teach one family',()=>{
 for(const id of ['V2_ORB_PULLBACK','V2_SPY_ORB_RSI_MACD_SHORT','RESEARCH_CTX_ORB_ATR10_V2']) assert.equal(family(id),'Opening-Range Breakout (ORB)');
});
test('source aliases share lessons but distinct concepts stay distinct',()=>{
 assert.equal(family('RESEARCH_FAILED_RANGE_V2'),family('V2_FAILED_OR_BREAK_VWAP_REVERSION'));
 assert.equal(family('RESEARCH_QQQ_TREND_V2'),family('V2_SPY_TREND_CONT'));
 assert.equal(family('CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'),family('V2_VWAP_PULLBACK'));
 assert.notEqual(family('V2_VWAP_REVERSION'),family('V2_VWAP_PULLBACK'));
 assert.notEqual(family('V2_TSLA_TWO_LEG_TREND_PULLBACK'),family('V2_SPY_TREND_CONT'));
});
test('unknown families retain identity rather than borrowing a different lesson',()=>{
 assert.equal(learningFamily({strategy_id:'UNKNOWN',display_name:'My setup'}),'My setup');
});
