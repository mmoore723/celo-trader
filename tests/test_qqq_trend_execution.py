import unittest
import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pandas as pd

from config.research_order_specs import execution_id
from config.admin_strategy_overrides import updates
from config.strategy_catalog import enabled_reviewed_strategy_ids, reviewed_strategy_integrity_errors
from strategies import research_orders, spy_trend_continuation_v2 as native
from strategies.market_structure import StructureSignal, Side
from trading.cross_ticker_shadow import evaluate_bar_strategy
from trading.research_order_exit import evaluate_exit
from strategy_health.pair_recommendations import assess, recommendations
from tests.test_pair_recommendations import trades
from tests.test_spy_trend_continuation_v2 import SpyTrendContinuationV2Tests

SID = 'RESEARCH_QQQ_TREND_V2'
SOURCE = 'V2_SPY_TREND_CONT'


class QqqTrendExecutionTests(unittest.TestCase):
    def setUp(self):
        research_orders._emitted.clear()
        native._emitted_trigger_by_session.clear()
        native._active_breakout_by_session.clear()

    def test_registration_and_grants_do_not_change_spy_or_risk(self):
        self.assertEqual({}, reviewed_strategy_integrity_errors())
        self.assertEqual(SID, execution_id(SOURCE,'2.1.0','QQQ'))
        self.assertEqual(SOURCE, execution_id(SOURCE,'2.1.0','SPY'))
        self.assertEqual('APPROVED_'+SOURCE, execution_id(SOURCE,'2.1.0','AAPL'))
        base={'paper_trading':True, 'risk_per_trade':.03, 'strategy_spy_trend_cont_v2_enabled':True}
        changes=updates(base,SOURCE,'QQQ','2.1.0',True,'admin',exit_minutes=90,contract_policy='closest_otm_150_1000')
        self.assertNotIn('paper_trading',changes)
        self.assertNotIn('risk_per_trade',changes)
        self.assertNotIn('strategy_spy_trend_cont_v2_enabled',changes)
        for paper in (True,False):
            self.assertIn(SID,enabled_reviewed_strategy_ids({**base,**changes,'paper_trading':paper},ticker='QQQ'))
            self.assertNotIn(SID,enabled_reviewed_strategy_ids({**base,**changes,'paper_trading':paper},ticker='SPY'))
        with self.assertRaises(ValueError): updates(base,SID,'AAPL','2.1.0',True,'admin')

    def test_research_and_order_entry_parity_and_deduplication(self):
        now=datetime(2026,11,3,11,1)
        frame=pd.DataFrame({'time':[now], 'open':[101.], 'high':[102.], 'low':[100.], 'close':[101.]})
        candidate=StructureSignal(Side.LONG,now-timedelta(minutes=1),101.,100.,103.,{'prior_high':100.5,'atr':1.})
        config=updates({},SOURCE,'QQQ','2.1.0',True,'admin',exit_minutes=90,contract_policy='closest_otm_150_1000')
        with patch.object(native,'_complete_five_minute_bars',return_value=SpyTrendContinuationV2Tests._completed_bars()), patch.object(native,'TrendContinuation') as engine, patch('config.get_settings',return_value=config):
            engine.return_value.evaluate.return_value=candidate
            shadow=evaluate_bar_strategy(SOURCE,native.evaluate,frame,ticker='QQQ',account_scope='test')
            order=research_orders.evaluate(frame,ticker='QQQ',execution_scope='test',now=now,strategy_id=SID)
            self.assertEqual(shadow.direction,order.direction)
            self.assertEqual(shadow.trigger_bar,order.trigger_bar)
            for field in ('v2_stop','v2_target','v2_entry_reference'):
                self.assertEqual(shadow.meta[field],order.meta[field])
            self.assertEqual(90,order.meta['selected_test_policy']['exit_minutes'])
            self.assertEqual('QQQ',order.meta['selected_test_policy']['ticker'])
            self.assertIsNone(research_orders.evaluate(frame,ticker='QQQ',execution_scope='test',now=now,strategy_id=SID))
            self.assertIsNotNone(research_orders.evaluate(frame,ticker='QQQ',execution_scope='other-account',now=now,strategy_id=SID))
            self.assertIsNone(research_orders.evaluate(frame,ticker='SPY',execution_scope='test',now=now,strategy_id=SID))

    def test_selected_exit_native_exit_and_session_exit(self):
        from config.research_pair_policy import build
        start=datetime(2026,11,3,13,tzinfo=ZoneInfo('America/New_York'))
        meta={'strategy_version':'2.1.0','research_order_route':'exact_research_v1'}
        trade={'strategy_id':SID,'ticker':'QQQ','strategy_context_json':json.dumps(meta)}
        self.assertEqual((True,'research_qqq_trend_30m'),evaluate_exit(trade,start,start+timedelta(minutes=30),None))
        meta['selected_test_policy']=build(SID,'QQQ','2.1.0',90,'closest_otm_150_1000')
        trade['strategy_context_json']=json.dumps(meta)
        self.assertEqual((False,'hold'),evaluate_exit(trade,start,start+timedelta(minutes=30),None))
        self.assertEqual((True,'selected_test_90m'),evaluate_exit(trade,start,start+timedelta(minutes=90),None))
        self.assertEqual((True,'research_session_close'),evaluate_exit(trade,start,start.replace(hour=15,minute=55),None))

    def test_qualified_qqq_recommendation_is_actionable_not_spy_mislabeled(self):
        matrix={'strategies':[{'strategy_id':SOURCE,'version':'2.1.0','display_name':'Trend Continuation',
            'pairs':[{'ticker':'QQQ','tradable':False,'research_contract_profile':'research_contracts_v1',
                      'recommendation':assess(trades([20,20,-10,20,-10]*4))}]}]}
        result=recommendations(matrix,{'paper_trading':True})['recommendations'][0]
        self.assertEqual(SID,result['strategy_id'])
        self.assertTrue(result['can_enable'])
        self.assertIsNone(result['blocker'])

    def test_selected_timer_submits_exit_even_during_quote_outage(self):
        from tests.test_failed_range_deadline import FailedRangeDeadlineTests
        from tests.test_research_order_execution import position
        from config.research_pair_policy import build
        trade=position(SID,selected_test_policy=build(SID,'QQQ','2.1.0',90,'closest_otm_150_1000'))
        with patch('tests.test_failed_range_deadline.position',return_value=trade):
            broker,market,state=FailedRangeDeadlineTests().run_case('2026-10-14T12:05:28-04:00')
        broker.place_option_order.assert_called_once()
        order=broker.place_option_order.call_args.kwargs
        self.assertEqual('selected_test_90m',order['order_context']['exit_reason'])
        self.assertEqual('market',order['order_type'])
        market.get_option_quote.assert_not_called()
