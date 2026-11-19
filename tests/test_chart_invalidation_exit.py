import json
import sqlite3
import unittest
from datetime import timedelta
import pandas as pd
from trading.chart_invalidation_exit import SPEC, REASON, check, apply, validate
from trading.premium_policy import evaluate, scope, fingerprint, freeze_selection
from trading.trend_profit_exit import policy_label
from config.qqq_chart_activation import approved_updates
from tests.test_adverse_candle_exit import T,quote

class ChartExitTests(unittest.TestCase):
 def setUp(self):
  self.policy=dict(rule='trend_partial_profit',version='premium-exits-v2',account='A',mode='paper',strategy='RESEARCH_QQQ_TREND_V2',ticker='QQQ',strategy_version='2.1.0',approval_id='test',gain_pct=10,giveback_pct=10,replace_native_exit=True,chart_invalidation_exit=dict(SPEC))
  self.policy['fingerprint']=fingerprint(self.policy)
  self.trade=dict(id=1,paper=True,broker_account_id='A',strategy_id='RESEARCH_QQQ_TREND_V2',ticker='QQQ',entry_time=T.isoformat(),entry_price=2,contracts=4,contract_symbol='TEST',option_type='call',strategy_context_json={'v2_stop':100,'premium_exit_policy':self.policy})
  self.at=T+timedelta(minutes=5)
  self.frame=pd.DataFrame([{'time':T,'close':99}])
 def run_apply(self,**kw):
  args=dict(trade=self.trade,quantity=4,sold=0,quote=quote(1.99,self.at),now=self.at,frame=self.frame);args.update(kw)
  return apply({},**args)
 def test_call_and_put_no_option_loss_requirement(self):
  self.assertEqual((True,REASON),self.run_apply()[1])
  self.assertEqual((True,REASON),self.run_apply(trade={**self.trade,'option_type':'put'},frame=self.frame.assign(close=101))[1])
 def test_wick_equal_and_good_close_do_not_trigger(self):
  for close in (100,101):self.assertIsNone(self.run_apply(frame=self.frame.assign(close=close,low=98))[1])
 def test_forming_preentry_stale_missing_duplicate_invalid(self):
  self.assertFalse(check(self.trade,self.frame,self.at-timedelta(seconds=1)).get('broken'))
  self.assertFalse(check({**self.trade,'entry_time':(T+timedelta(seconds=1)).isoformat()},self.frame,self.at).get('broken'))
  for f in (None,self.frame.iloc[:0],pd.concat([self.frame,self.frame]),self.frame.assign(close=float('nan')),self.frame.assign(time=T-timedelta(minutes=5))):
   self.assertFalse(check(self.trade,f,self.at).get('broken'))
 def test_missing_level_not_option_stop_fallback(self):
  t={**self.trade,'strategy_context_json':{},'stop_price':100}
  self.assertEqual('original_setup_level_unavailable',check(t,self.frame,self.at)['status'])
 def test_quote_validation(self):
  for q in (None,quote(1.9,self.at-timedelta(seconds=20)),{**quote(1.9,self.at),'bidsize':1}):self.assertIsNone(self.run_apply(quote=q)[1])
 def test_durable_trigger_and_activation(self):
  s,d=self.run_apply()
  args=dict(trade=self.trade,quantity=4,sold=0,quote=None,now=self.at,frame=None)
  self.assertEqual(d,apply(json.loads(json.dumps(s)),**args)[1])
  self.assertIsNone(apply({'activated':True},**args)[1])
  self.assertIsNone(self.run_apply(sold=1)[1])
 def test_scope_and_no_stacked_protection(self):
  for changes in ({'ticker':'SPY'},{'adverse_candle_failsafe':{'loss_pct':10}},{'chart_invalidation_exit':{'timeframe_minutes':1,'consecutive_candles':1}}):
   with self.assertRaises(ValueError):validate({**self.policy,**changes})
 def test_database_evaluation_and_profit_priority(self):
  c=sqlite3.connect(':memory:')
  c.execute('CREATE TABLE trades(id,status,paper,broker_account_id,strategy_context_json,contracts,parent_trade_id,exit_reason)')
  c.execute('INSERT INTO trades VALUES(1,\'open\',1,\'A\',?,4,NULL,NULL)',(json.dumps(self.trade['strategy_context_json']),))
  self.assertEqual((True,REASON),evaluate(c,self.trade,quote(1.99,self.at),self.at,five_minute_bars=self.frame))
  state=json.loads(c.execute('select strategy_context_json from trades').fetchone()[0])
  self.assertEqual(100,state['premium_exit_state']['chart_exit_check']['original_setup_level'])
  self.assertEqual((True,REASON),evaluate(c,self.trade,None,self.at+timedelta(seconds=1)))
  c.execute('update trades set strategy_context_json=?',(json.dumps(self.trade['strategy_context_json']),))
  self.assertEqual((True,'stage1_trend_profit'),evaluate(c,self.trade,quote(2.2,self.at),self.at,five_minute_bars=self.frame))
  c.close()
 def test_approval_preserves_other_settings_and_old_frozen_trades(self):
  old={**self.policy,'chart_invalidation_exit':None,'adverse_candle_failsafe':{'timeframe_minutes':5,'consecutive_candles':3,'loss_pct':10}};old['fingerprint']=fingerprint(old)
  key=scope('A','RESEARCH_QQQ_TREND_V2','QQQ','2.1.0')
  settings=dict(paper_trading=True,active_broker_account_id='A',premium_exit_paper_assignments={key:old,'other':{'unchanged':True}},risk_per_trade=.02)
  before=json.dumps(settings,sort_keys=True)
  updates=approved_updates(settings)
  self.assertEqual(before,json.dumps(settings,sort_keys=True))
  self.assertEqual({'premium_exit_paper_assignments'},set(updates))
  self.assertEqual({'unchanged':True},updates['premium_exit_paper_assignments']['other'])
  frozen=freeze_selection({**settings,**updates},'RESEARCH_QQQ_TREND_V2','QQQ','2.1.0')['premium_exit_policy']
  self.assertEqual(SPEC,frozen['chart_invalidation_exit']);self.assertIsNone(frozen['adverse_candle_failsafe'])
  self.assertIn('original setup',policy_label(frozen))
  with self.assertRaises(ValueError):approved_updates({**settings,'paper_trading':False})
 def test_retry_and_session_priority(self):
  from trading.position_manager.exit_preflight import full_exit_reason
  from zoneinfo import ZoneInfo
  self.assertEqual(REASON,full_exit_reason(self.trade,{'exit_pending_reason':REASON},self.at))
  end=T.astimezone(ZoneInfo('America/New_York')).replace(hour=15,minute=55)
  self.assertEqual('research_session_close',full_exit_reason(self.trade,{'exit_pending_reason':REASON},end))
