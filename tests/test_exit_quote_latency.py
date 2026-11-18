"""Trade374 rejection replay and isolation of entry reads from protection."""
import json
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
import requests
from broker.read_budget import (market_read_budget, entry_read_scope,
                               start_entry_read_budget, request_policy)
from strategy_health.premium_rules import quote_validation
from trading.position_manager.quote_check import refresh_exit_quote

T = datetime(2026,11,18,17,30,tzinfo=timezone.utc)
SYMBOL = 'SPY261125P00726000'
def quote(bid, second, size=133):
    return dict(symbol=SYMBOL,bid=bid,ask=bid+.06,bidsize=size,asksize=107,
                mid=bid+.03,bid_date=(T+timedelta(seconds=second)).timestamp()*1000,
                ask_date=(T+timedelta(seconds=second)).timestamp()*1000)


class QuoteLatencyTests(unittest.TestCase):
    def test_actual_trade374_quotes_explain_every_rejection(self):
        for received,stamp,bid,size,reasons in [
            (15.578323,0,5.93,133,['bid_stale','ask_stale']),
            (20.761193,-1,5.94,141,['bid_stale','ask_stale']),
            (45.609841,33,5.96,32,['bid_stale','ask_stale']),
            (47.883317,46,6.04,1,['insufficient_bid_size']),
            (77.460985,76,5.87,152,[])]:
            value,details=quote_validation(quote(bid,stamp,size),T+timedelta(seconds=received),3,SYMBOL)
            self.assertEqual(reasons,details['reasons'])
            self.assertEqual(not reasons,value is not None)

    def test_refresh_uses_actual_clock_and_never_accepts_old_or_small_quote(self):
        trade=dict(contracts=3,contract_symbol=SYMBOL)
        market=Mock();market.get_option_quote.return_value=quote(5.96,21,1)
        now=T+timedelta(seconds=22)
        q,at=refresh_exit_quote(market,trade,quote(5.93,0),lambda:now)
        self.assertEqual(now,at)
        self.assertIsNone(quote_validation(q,at,3,SYMBOL)[0])
        market.get_option_quote.assert_called_once()
        market.reset_mock()
        q,at=refresh_exit_quote(market,trade,quote(5.96,21,30),lambda:now)
        market.get_option_quote.assert_not_called()
        self.assertIsNotNone(quote_validation(q,at,3,SYMBOL)[0])

    def test_budget_cannot_change_account_requests_and_resets_after_exception(self):
        with patch('broker.read_budget.time.monotonic',return_value=10):
            with market_read_budget(5):
                self.assertEqual((2,1),request_policy(True))
                self.assertEqual((10,3),request_policy(False))
                with patch('broker.read_budget.time.monotonic',return_value=16):
                    with self.assertRaises(requests.Timeout):request_policy(True)
                    self.assertEqual((10,3),request_policy(False))
            self.assertEqual((10,3),request_policy(True))
        @entry_read_scope
        def scan():
            start_entry_read_budget([{'id':374}])
            self.assertEqual(1,request_policy(True)[1])
            raise ValueError('stop')
        with self.assertRaises(ValueError):scan()
        self.assertEqual((10,3),request_policy(True))

    def test_tradier_market_timeout_does_not_retry_with_open_position_budget(self):
        from broker.tradier_core import TradierCoreMixin
        client=object.__new__(TradierCoreMixin);client.base='https://example.test';client.headers={}
        with patch('broker.tradier_core.requests.get',side_effect=requests.Timeout('test')) as get, \
             patch('broker.tradier_core.log_event'),patch('broker_health.record_broker_error'):
            with market_read_budget(5):
                with self.assertRaises(requests.Timeout):client._get('/markets/timesales')
            self.assertEqual(1,get.call_count)
            self.assertLessEqual(get.call_args.kwargs['timeout'],2)

    def test_account_request_keeps_existing_retry_even_inside_market_budget(self):
        from broker.tradier_core import TradierCoreMixin
        client=object.__new__(TradierCoreMixin);client.base='https://example.test';client.headers={}
        with patch('broker.tradier_core.requests.get',side_effect=requests.Timeout('test')) as get, \
             patch('broker.tradier_core.log_event'),patch('broker_health.record_broker_error'), \
             patch('broker.common.time.sleep'):
            with market_read_budget(5):
                with self.assertRaises(requests.Timeout):client._get('/accounts/account/orders')
            self.assertEqual(3,get.call_count)
            self.assertTrue(all(c.kwargs['timeout']==10 for c in get.call_args_list))

    def test_replacement_exit_does_not_fetch_unused_native_timeframes(self):
        from tests.test_profit_replacement import ReplacementTests
        from trading.premium_policy import fingerprint
        from trading.adverse_candle_exit import SPEC,REASON
        from trading.position_manager.manage import _manage_open_position
        trade=ReplacementTests().trade('V2_SPY_TREND_CONT','SPY')
        trade.update(contract_symbol=SYMBOL,contracts=3,entry_price=8.94,
                     entry_time='2026-11-18T11:21:34-05:00',option_type='put')
        ctx=json.loads(trade['strategy_context_json']);policy=ctx['premium_exit_policy']
        policy['adverse_candle_failsafe']=dict(SPEC);policy['fingerprint']=fingerprint(policy)
        trade['strategy_context_json']=json.dumps(ctx)
        state={'positions':{}}
        now=T+timedelta(seconds=17)
        broker=Mock();broker.get_positions.return_value=[dict(symbol=SYMBOL,current_price=5.93)]
        broker.get_session_bars.return_value=([],True,None)
        market=Mock();market.get_option_quote.return_value=quote(5.93,16)
        seen=[]
        def evaluate(t,q,at,**kw):
            self.assertEqual(now,at)
            self.assertIsNotNone(quote_validation(q,at,3,SYMBOL)[0])
            seen.append('evaluate')
            return True,REASON
        with ExitStack() as stack:
            for path,value in [
                ('trading.position_manager.manage.get_user_state',state),
                ('trading.position_manager.manage.get_user_risk',SimpleNamespace(ORB_STOP_PCT=.2,STAGE1_ATR_TARGET_MULT=2,STAGE1_TARGET_MIN_PCT=.3)),
                ('trading.position_manager.manage.get_user_trade_log',Mock()),
                ('trading.position_manager.manage._now_et',now),
                ('trading.research_session_clock.session_close_if_open',T.replace(hour=21,minute=0)),
                ('config.get_settings',{'paper_trading':True})]:
                stack.enter_context(patch(path,return_value=value))
            for path in ['database.record_paper_option_quote','database.log_event','config.atomic_update_json',
                         'risk.recover_peak_price','risk.persist_peak_price',
                         'trading.position_manager.manage._persist_exit_latch']:
                stack.enter_context(patch(path,return_value=None))
            stack.enter_context(patch('trading.premium_policy.evaluate_position',side_effect=evaluate))
            close=stack.enter_context(patch('trading.position_manager.close._close_position'))
            _manage_open_position(broker,market,trade,10000)
            self.assertEqual(['evaluate'],seen)
            close.assert_called_once()
            self.assertEqual(REASON,close.call_args.args[3])
            self.assertEqual(['5Min'],[c.args[1] for c in broker.get_session_bars.call_args_list])
            broker.get_bars.assert_not_called()
