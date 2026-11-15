import json
import unittest
from datetime import timedelta
from unittest.mock import Mock,patch
import pandas as pd
from trading.adverse_candle_exit import configured_frame,candle_check,validate,apply,is_failsafe_reason
from trading.trend_profit_exit import advance,partial_target,policy_label,PARTIAL
from tests.test_adverse_candle_exit import T,quote
from tests.test_engine_parameters import ProfitConfigurationTests
from config import engine_parameters as ep
from trading.premium_policy import freeze_selection

class PartialConfigurationTests(unittest.TestCase):
 def test_save_freeze_new_controls_without_mutating_assignment(self):
  settings,v=ProfitConfigurationTests().settings();before=json.dumps(settings,sort_keys=True)
  sid='V2_SPY_TREND_CONT';view=ep.describe(settings,sid,'SPY',v)
  values=dict(gain_pct=10,giveback_pct=10,partial_sell_pct=30,adverse_candle_failsafe=dict(timeframe_minutes=4,consecutive_candles=3,loss_pct=10))
  update=ep.save(settings,sid,'SPY',v,view['revision'],{},'test',profit=values)
  self.assertEqual(before,json.dumps(settings,sort_keys=True))
  policy=freeze_selection({**settings,**update},sid,'SPY',v)['premium_exit_policy']
  self.assertEqual(30,policy['partial_sell_pct']);self.assertEqual(4,policy['adverse_candle_failsafe']['timeframe_minutes'])
  self.assertIn('Take 30%',policy_label(policy));self.assertIn('4-minute',policy_label(policy))
  self.assertNotIn('partial_sell_pct',freeze_selection(settings,sid,'SPY',v)['premium_exit_policy'])
 def test_rounding_and_restarted_partial_target(self):
  self.assertEqual(4,partial_target(9));self.assertEqual(2,partial_target(9,30));self.assertEqual(0,partial_target(1,30))
  at=T+timedelta(seconds=1)
  s,r=advance({},entry=2,quantity=10,sold=0,quote=quote(2.2,at),now=at,symbol='TEST',gain_pct=10,giveback_pct=10,partial_sell_pct=30)
  self.assertEqual((True,PARTIAL),r);self.assertEqual(3,s['partial_target'])
  s=json.loads(json.dumps(s))
  s,r=advance(s,entry=2,quantity=9,sold=1,quote=None,now=at+timedelta(seconds=1),symbol='TEST',gain_pct=10,giveback_pct=10,partial_sell_pct=30)
  self.assertEqual((True,PARTIAL),r);self.assertEqual(3,s['partial_target'])
  s,r=advance(s,entry=2,quantity=7,sold=3,quote=None,now=at+timedelta(seconds=2),symbol='TEST',gain_pct=10,giveback_pct=10,partial_sell_pct=30)
  self.assertFalse(r[0]);self.assertNotIn('partial_signal',s)
 def test_custom_candles_complete_gap_duplicate_and_timeout(self):
  start=T.replace(minute=0,second=0,microsecond=0);now=start+timedelta(minutes=16,seconds=20)
  rows=[dict(time=start+timedelta(minutes=i),close=100-i) for i in range(17)]
  policy={'configuration_editor':1,'adverse_candle_failsafe':dict(timeframe_minutes=4,consecutive_candles=3,loss_pct=10)}
  client=Mock();client.get_session_bars.return_value=([1],None,True)
  def build(data):
   with patch('signals.bars_to_df',return_value=pd.DataFrame(data)):return configured_frame(client,'SPY',policy,now,{},None)
  frame=build(rows);self.assertEqual(4,len(frame));self.assertTrue(candle_check(frame,start,now,'call',3,4)['adverse'])
  self.assertFalse(candle_check(build(rows[:7]+rows[8:]),start,now,'call',3,4).get('adverse',False))
  self.assertFalse(candle_check(build(rows+[rows[7]]),start,now,'call',3,4).get('adverse',False))
  s,r=apply({},trade=dict(entry_time=start,option_type='call',entry_price=2,contract_symbol='TEST'),quantity=9,sold=0,quote=quote(1.8,now),now=now,frame=frame,spec=policy['adverse_candle_failsafe'])
  self.assertEqual((True,'adverse_3x4m_10pct_loss'),r);self.assertTrue(is_failsafe_reason(r[1]))
  client.get_session_bars.side_effect=TimeoutError
  self.assertIsNone(configured_frame(client,'SPY',policy,now,{},frame))
 def test_every_supported_interval_uses_only_completed_bars(self):
  from trading.adverse_candle_exit import TIMEFRAMES
  start=T.replace(hour=10,minute=0,second=0,microsecond=0)
  for minutes in TIMEFRAMES:
   now=start+timedelta(minutes=minutes*4,seconds=20)
   bars=pd.DataFrame([dict(time=start+timedelta(minutes=minutes*i),close=100-i) for i in range(5)])
   check=candle_check(bars,start,now,'call',3,minutes)
   self.assertTrue(check['adverse'],minutes)
   self.assertEqual([100,99,98,97],check['closes'])
 def test_default_frame_unchanged_and_invalid_inputs_rejected(self):
  frame=object();client=Mock()
  self.assertIs(frame,configured_frame(client,'SPY',{},T,{},frame));client.get_session_bars.assert_not_called()
  for percentage in [0,100,True,float('nan')]:
   with self.assertRaises(ValueError):ep.validate_profit(dict(gain_pct=10,giveback_pct=10,partial_sell_pct=percentage,adverse_candle_failsafe=None))
  for tf in [0,7,True,61]:
   with self.assertRaises(ValueError):validate({'configuration_editor':1,'adverse_candle_failsafe':dict(timeframe_minutes=tf,consecutive_candles=3,loss_pct=10)})

from tests.test_execution_recovery_integration import RecoveryIntegrationTests
from tests import test_execution_recovery as fixtures
from database.execution_recovery import connect
from trading.premium_policy import evaluate,fingerprint
from trading.trend_profit_exit import partial_remaining,RULE
from strategy_health.premium_rules import VERSION
from broker.recovery import reconcile_orders
from datetime import datetime

class CustomPartialBrokerTests(RecoveryIntegrationTests):
 def test_custom_partial_actual_fills_restart_and_duplicates(self):
  context=self.context()
  policy=dict(rule=RULE,version=VERSION,account=fixtures.ACCOUNT,mode='paper',strategy='V2_SPY_TREND_CONT',ticker='SPY',strategy_version='2.1.0',approval_id=1,configuration_editor=1,gain_pct=10,giveback_pct=10,partial_sell_pct=30)
  policy['fingerprint']=fingerprint(policy)
  context['entry_record']['strategy_context_json']=json.dumps({'premium_exit_policy':policy})
  self.next_qty='10'
  entry=self.client.place_option_order(fixtures.SYMBOL,10,'buy',limit_price=1.6,position_intent='buy_to_open',order_context=context)
  parent=entry['accounted_trade_id'];trade=next(r for r in self.rows() if r['id']==parent)
  now=datetime.fromisoformat(fixtures.FILL_TIME.replace('Z','+00:00'))+timedelta(seconds=2)
  q=dict(symbol=fixtures.SYMBOL,bid=1.8,ask=1.82,bidsize=20,asksize=20,bid_date=now.timestamp()*1000,ask_date=now.timestamp()*1000)
  with connect(self.path) as conn:self.assertEqual((True,PARTIAL),evaluate(conn,trade,q,now))
  with patch('database.get_conn',side_effect=lambda:connect(self.path)):
   self.assertEqual(3,partial_remaining(trade))
   self.next_status,self.next_qty,self.next_price='canceled','1','1.8'
   self.client.place_option_order(fixtures.SYMBOL,3,'sell',limit_price=1.8,position_intent='sell_to_close',order_context=dict(trade_id=parent,expected_contracts=10,exit_reason=PARTIAL+'_profit_take'))
   restarted=self.make_client();reconcile_orders(restarted)
   trade=next(r for r in self.rows() if r['id']==parent)
   self.assertEqual(2,partial_remaining(trade))
   self.next_status,self.next_qty='filled','2'
   ctx=dict(trade_id=parent,expected_contracts=9,exit_reason=PARTIAL+'_profit_take')
   restarted.place_option_order(fixtures.SYMBOL,2,'sell',limit_price=1.8,position_intent='sell_to_close',order_context=ctx)
   count=len(self.submissions)
   restarted.place_option_order(fixtures.SYMBOL,2,'sell',limit_price=1.8,position_intent='sell_to_close',order_context=ctx)
   self.assertEqual(count,len(self.submissions))
   trade=next(r for r in self.rows() if r['id']==parent)
   self.assertEqual(7,trade['contracts']);self.assertEqual(0,partial_remaining(trade))
