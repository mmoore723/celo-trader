import assert from "node:assert/strict";
import test from "node:test";
import {closedTradeText} from "../src/lib/closedTradeView.js";

const pair = {ticker:"TSLA",version:"2.1.0",completed_trades:2,profit_factor:0,realized_pnl:-460};
test('Current closed losses show PF zero and actual total P&L', () => {
  assert.equal(closedTradeText(pair), 'TSLA · PF 0.00 · 2 closed · −$460.00');
});
test('No completed results never invents zero-dollar performance', () => {
  assert.equal(closedTradeText({...pair,completed_trades:0,profit_factor:null,realized_pnl:null}),
    'TSLA · No closed trades for v2.1.0');
});
test('Win-only result does not imply a proven numerical PF', () => {
  assert.match(closedTradeText({...pair,profit_factor:'infinite',realized_pnl:30}), /No losses yet/);
});
