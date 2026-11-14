import json
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pandas as pd
from trading.adverse_candle_exit import candle_check,apply,SPEC,REASON
from trading.trend_profit_exit import advance,replacement_policy
from trading.premium_policy import fingerprint,freeze_selection,scope
from tests.test_profit_replacement import ReplacementTests

T=datetime(2026,11,13,15,0,tzinfo=timezone.utc)
def frame(call=True):
 return pd.DataFrame([{'time':T+timedelta(minutes=5*(i-1)),'close':100-i if call else 100+i} for i in range(5)])
def quote(bid,at):return dict(symbol='TEST',bid=bid,ask=bid+.01,bidsize=20,asksize=20,bid_date=at.timestamp()*1000,ask_date=at.timestamp()*1000)

class AdverseTests(unittest.TestCase):
 def trade(self,option_type='call'):
  return dict(entry_time=T.isoformat(),entry_price=2,contract_symbol='TEST',option_type=option_type)
 def test_both_directions_and_full_closed_candles(self):
  for call in (True,False):
   t=self.trade('call' if call else 'put');at=T+timedelta(minutes=15)
   self.assertTrue(candle_check(frame(call),T,at,t['option_type'])['adverse'])
   s,r=apply({},trade=t,quantity=9,sold=0,quote=quote(1.8,at),now=at,frame=frame(call))
   self.assertEqual((True,REASON),r)
   self.assertEqual('triggered',s['failsafe_status'])
 def test_forming_missing_duplicate_flat_and_pre_entry_do_not_trigger(self):
  f=frame();at=T+timedelta(minutes=15)
  for x in (None,f.iloc[:3],pd.concat([f,f.iloc[[2]]]),f.assign(close=100)):
   self.assertFalse(candle_check(x,T,at,'call').get('adverse'))
  self.assertFalse(candle_check(f,T,at-timedelta(seconds=1),'call').get('adverse'))
  self.assertFalse(candle_check(f,T+timedelta(seconds=1),at,'call').get('adverse'))
 def test_both_price_and_candles_required_and_bad_quotes(self):
  at=T+timedelta(minutes=15)
  for q in (None,quote(1.81,at),quote(1.8,at-timedelta(seconds=30)),{**quote(1.8,at),'ask':1.7},{**quote(1.8,at),'bidsize':1}):
   self.assertIsNone(apply({},trade=self.trade(),quantity=9,sold=0,quote=q,now=at,frame=frame())[1])
 def test_activation_and_partial_fill_disable_after_restart(self):
  at=T+timedelta(minutes=15)
  s,_=advance({},entry=2,quantity=9,sold=0,quote=quote(2.2,at),now=at,symbol='TEST',gain_pct=10,giveback_pct=10)
  for state,sold in ((json.loads(json.dumps(s)),0),({},1)):
   result,decision=apply(state,trade=self.trade(),quantity=8,sold=sold,quote=quote(1.7,at),now=at,frame=frame())
   self.assertIsNone(decision);self.assertEqual('disabled_after_profit_activation',result['failsafe_status'])
 def test_trigger_is_durable_through_quote_failure_and_restart(self):
  at=T+timedelta(minutes=15)
  s,_=apply({},trade=self.trade(),quantity=9,sold=0,quote=quote(1.8,at),now=at,frame=frame())
  self.assertEqual((True,REASON),apply(json.loads(json.dumps(s)),trade=self.trade(),quantity=9,sold=0,quote=None,now=at+timedelta(seconds=1),frame=None)[1])
 def test_old_policy_keeps_no_failsafe_and_new_policy_frozen(self):
  t=ReplacementTests().trade('V2_SPY_TREND_CONT','SPY')
  old=replacement_policy(t);new={**old,'adverse_candle_failsafe':dict(SPEC)};new['fingerprint']=fingerprint(new)
  settings=dict(paper_trading=True,active_broker_account_id='A',premium_exit_paper_assignments={scope('A','V2_SPY_TREND_CONT','SPY','test'):new})
  frozen=freeze_selection(settings,'V2_SPY_TREND_CONT','SPY','test')
  self.assertNotIn('adverse_candle_failsafe',replacement_policy(t))
  self.assertEqual(SPEC,frozen['premium_exit_policy']['adverse_candle_failsafe'])
  new['adverse_candle_failsafe']['loss_pct']=19;new['fingerprint']=fingerprint(new)
  with self.assertRaises(ValueError):freeze_selection(settings,'V2_SPY_TREND_CONT','SPY','test')
  self.assertEqual({},freeze_selection({**settings,'paper_trading':False},'V2_SPY_TREND_CONT','SPY','test'))
 def test_session_priority_over_pending_failsafe(self):
  from trading.position_manager.exit_preflight import full_exit_reason
  t=ReplacementTests().trade('V2_SPY_TREND_CONT','SPY')
  at=T.replace(hour=20,minute=55)
  self.assertEqual('research_session_close',full_exit_reason(t,{'exit_pending_reason':REASON},at))

from tests.test_execution_recovery_integration import RecoveryIntegrationTests
from tests import test_execution_recovery as fixtures
from database.execution_recovery import connect
from trading.premium_policy import evaluate
from broker.recovery import reconcile_orders

class AdverseBrokerTests(RecoveryIntegrationTests):
 def test_full_exit_partial_fill_restart_and_duplicate_recovery(self):
  context=self.context();policy=ReplacementTests().trade('V2_SPY_TREND_CONT','SPY')
  p=json.loads(policy['strategy_context_json'])['premium_exit_policy']
  p.update(account=fixtures.ACCOUNT,strategy_version='2.1.0',adverse_candle_failsafe=dict(SPEC));p['fingerprint']=fingerprint(p)
  context['entry_record']['strategy_context_json']=json.dumps({'premium_exit_policy':p})
  self.next_qty='9'
  entry=self.client.place_option_order(fixtures.SYMBOL,9,'buy',limit_price=1.6,position_intent='buy_to_open',order_context=context)
  parent=entry['accounted_trade_id'];trade=next(r for r in self.rows() if r['id']==parent)
  from strategy_health.premium_rules import clock
  start=clock(trade['entry_time']);base=start.replace(minute=start.minute//5*5,second=0,microsecond=0);at=base+timedelta(minutes=20)
  bars=pd.DataFrame([{'time':base+timedelta(minutes=5*i),'close':100-i} for i in range(4)])
  q=quote(1.44,at);q['symbol']=fixtures.SYMBOL
  with connect(self.path) as conn:
   self.assertEqual((True,REASON),evaluate(conn,trade,q,at,five_minute_bars=bars))
  self.next_status,self.next_qty,self.next_price='canceled','4','1.44'
  self.client.place_option_order(fixtures.SYMBOL,9,'sell',limit_price=1.44,position_intent='sell_to_close',order_context={'trade_id':parent,'expected_contracts':9,'exit_reason':REASON})
  restarted=self.make_client();reconcile_orders(restarted)
  trade=next(r for r in self.rows() if r['id']==parent)
  self.assertEqual(5,trade['contracts'])
  with connect(self.path) as conn:
   self.assertEqual((True,REASON),evaluate(conn,trade,None,at+timedelta(seconds=1)))
  self.next_status,self.next_qty='filled','5'
  ctx={'trade_id':parent,'expected_contracts':5,'exit_reason':REASON}
  restarted.place_option_order(fixtures.SYMBOL,5,'sell',limit_price=1.44,position_intent='sell_to_close',order_context=ctx)
  count=len(self.submissions)
  restarted.place_option_order(fixtures.SYMBOL,5,'sell',limit_price=1.44,position_intent='sell_to_close',order_context=ctx)
  self.assertEqual(count,len(self.submissions))
  self.assertEqual('closed',next(r for r in self.rows() if r['id']==parent)['status'])
