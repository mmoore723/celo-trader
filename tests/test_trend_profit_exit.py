import json
import unittest
from datetime import timedelta, datetime
from unittest.mock import patch
from trading.trend_profit_exit import advance, RULE, PARTIAL, RUNNER, partial_remaining
from trading.premium_policy import evaluate, fingerprint, freeze_selection, scope
from strategy_health.premium_rules import VERSION
from tests.test_premium_rules import T, quote
from tests.test_execution_recovery_integration import RecoveryIntegrationTests
from tests import test_execution_recovery as fixtures
from broker.recovery import reconcile_orders
from database.execution_recovery import connect

class TrendRulesTests(unittest.TestCase):
    def step(self, state, bid, seconds, quantity=9, sold=0):
        now=T+timedelta(seconds=seconds)
        q=quote(bid);q.update(bid_date=now.timestamp()*1000,ask_date=now.timestamp()*1000,bidsize=20)
        return advance(state,entry=1,quantity=quantity,sold=sold,quote=q,now=now,symbol='TEST')
    def test_partial_then_peak_giveback_and_partial_retry(self):
        s,r=self.step({},1.24,1);self.assertFalse(r[0])
        s,r=self.step(s,1.25,2);self.assertEqual(r,(True,PARTIAL));self.assertEqual(s['partial_target'],4)
        s,r=self.step(s,1.60,3,7,2);self.assertEqual(r,(True,PARTIAL))
        s=json.loads(json.dumps(s)) # persisted restart state
        s,r=self.step(s,1.50,4,5,4);self.assertFalse(r[0])
        s,r=self.step(s,1.45,5,5,4);self.assertEqual(r,(True,RUNNER))
        self.assertEqual(s['high_bid'],1.60)
    def test_one_contract_arms_without_selling_and_cost_floor(self):
        s,r=self.step({},1.25,1,1);self.assertFalse(r[0])
        s,r=self.step(s,1.1875,2,1);self.assertEqual(r,(True,RUNNER))
        s,r=self.step({},1.25,1,1)
        s,r=self.step(s,1.01,2,1);self.assertFalse(r[0])
    def test_invalid_quotes_cannot_arm(self):
        for q in (None,quote(1.4),dict(quote(1.4),ask=1.0)):
            s,r=advance({},entry=1,quantity=4,sold=0,quote=q,now=T+timedelta(seconds=60),symbol='TEST')
            self.assertFalse(r[0]);self.assertNotIn('high_bid',s)
    def test_live_freeze_and_scope(self):
        policy=dict(rule=RULE,version=VERSION,account='A',mode='paper',strategy='V2_SPY_TREND_CONT',ticker='SPY',strategy_version='2.1.0',approval_id=1)
        policy['fingerprint']=fingerprint(policy)
        settings=dict(paper_trading=True,active_broker_account_id='A',premium_exit_paper_assignments={scope('A',policy['strategy'],'SPY','2.1.0'):policy})
        self.assertEqual(freeze_selection(settings,policy['strategy'],'SPY','2.1.0')['premium_exit_policy'],policy)
        self.assertEqual(freeze_selection({**settings,'paper_trading':False},policy['strategy'],'SPY','2.1.0'),{})

class TrendBrokerTests(RecoveryIntegrationTests):
    def test_trend_partial_restart_duplicate_and_runner(self):
        from trading.recovery_state import restore_stage1
        context=self.context()
        policy=dict(rule=RULE,version=VERSION,account=fixtures.ACCOUNT,mode='paper',strategy='V2_SPY_TREND_CONT',ticker='SPY',strategy_version='2.1.0',approval_id=1)
        policy['fingerprint']=fingerprint(policy)
        context['entry_record']['strategy_context_json']=json.dumps({'premium_exit_policy':policy})
        self.next_qty='9'
        entry=self.client.place_option_order(fixtures.SYMBOL,9,'buy',limit_price=1.6,position_intent='buy_to_open',order_context=context)
        parent=entry['accounted_trade_id']
        now=datetime.fromisoformat(fixtures.FILL_TIME.replace('Z','+00:00'))+timedelta(seconds=2)
        def decide(bid,at):
            trade=next(r for r in self.rows() if r['id']==parent)
            q=dict(symbol=fixtures.SYMBOL,bid=bid,ask=bid+.02,bidsize=20,asksize=20,bid_date=at.timestamp()*1000,ask_date=at.timestamp()*1000)
            with connect(self.path) as conn:return evaluate(conn,trade,q,at)
        self.assertEqual(decide(2.,now),(True,PARTIAL))
        self.next_status,self.next_qty,self.next_price='canceled','2','2.00'
        self.client.place_option_order(fixtures.SYMBOL,4,'sell',limit_price=2.,position_intent='sell_to_close',order_context={'trade_id':parent,'expected_contracts':9,'exit_reason':PARTIAL+'_profit_take'})
        with patch('database.get_conn',side_effect=lambda:connect(self.path)):
            trade=next(r for r in self.rows() if r['id']==parent)
            self.assertEqual(partial_remaining(trade),2)
            state={'exit_pending_reason':PARTIAL};restore_stage1(trade,state);self.assertFalse(state['stage1_done'])
            self.assertEqual(decide(2.4,now+timedelta(seconds=1)),(True,PARTIAL))
            restarted=self.make_client();reconcile_orders(restarted)
            self.next_status,self.next_qty='filled','2'
            order_context={'trade_id':parent,'expected_contracts':7,'exit_reason':PARTIAL+'_profit_take'}
            restarted.place_option_order(fixtures.SYMBOL,2,'sell',limit_price=2.,position_intent='sell_to_close',order_context=order_context)
            submissions=len(self.submissions)
            restarted.place_option_order(fixtures.SYMBOL,2,'sell',limit_price=2.,position_intent='sell_to_close',order_context=order_context)
            self.assertEqual(len(self.submissions),submissions)
            trade=next(r for r in self.rows() if r['id']==parent)
            self.assertEqual(trade['contracts'],5);self.assertEqual(partial_remaining(trade),0)
            restore_stage1(trade,state);self.assertTrue(state['stage1_done']);self.assertNotIn('exit_pending_reason',state)
            self.assertEqual(decide(2.21,now+timedelta(seconds=2)),(False,'hold'))
            self.assertEqual(decide(2.20,now+timedelta(seconds=3)),(True,RUNNER))
            before=self.rows();reconcile_orders(self.make_client());self.assertEqual(self.rows(),before)
            # Real full-close path with mocked broker; a quote gap cannot lower the floor.
            from trading.position_manager.close import _close_position
            from unittest.mock import Mock
            self.next_status,self.next_qty,self.next_price='filled','5','2.20'
            with patch('trading.position_manager.close.get_user_state',return_value={'positions':{},'account_balance':4000}), patch('trading.position_manager.close.get_user_risk',return_value=Mock()), patch('trading.position_manager.close.get_user_trade_log',return_value=Mock()), patch('trading.position_manager.close.set_user_trade_log'), patch('config.atomic_update_json'), patch('database.log_event'), patch('database.record_paper_option_quote'), patch('database.link_broker_order_to_trade'), patch('ai_reasoning.narrator.narrate_exit'):
                _close_position(restarted,trade,1.5,RUNNER,bid_price=1.49)
            self.assertEqual(self.submissions[-1]['type'],'limit')
            self.assertGreaterEqual(float(self.submissions[-1]['limit_price']),1.64)
            self.assertEqual(next(r for r in self.rows() if r['id']==parent)['status'],'closed')


from tests.test_research_order_execution import position, candles, ATR10, SPECS, SimpleNamespace
class TrendManagerTests(unittest.TestCase):
    def test_trend_manager_submits_exact_partial_quantity(self):
        from contextlib import ExitStack
        from unittest.mock import Mock
        from zoneinfo import ZoneInfo
        from trading.position_manager.manage import _manage_open_position
        from strategy_health.context_orb_exit import metadata
        now = datetime(2026, 9, 10, 10, 8, tzinfo=ZoneInfo('America/New_York'))
        for paper in (True,):
            for stop in (False,):
                trade = position(ATR10, **metadata(SPECS[ATR10].source), or_midpoint=98)
                trade.update(ticker='SPY', entry_time='2026-09-10T10:05:01', paper=paper)
                tape = candles(); tape['volume'] = 100
                if stop: tape.loc[1, ['low', 'close']] = [97, 97]
                state = {'positions': {101: {'entry_time': trade['entry_time'], 'cached_underlying_df': tape,
                         'last_bar_fetch_minute': now.strftime('%Y-%m-%d %H:%M'), 'peak_price': 3, 'min_price': 2,
                         'last_position_narration_minute': now.strftime('%Y-%m-%d %H:%M')}}}
                broker = Mock()
                broker.base = 'https://paper-api.alpaca.markets'
                broker._get.return_value = {'timestamp': now.isoformat(), 'is_open': True,
                                            'next_close': now.replace(hour=16, minute=0).isoformat()}
                broker.get_positions.return_value = [{'symbol': 'CONTRACT', 'current_price': 2.65}]
                broker.get_session_bars.return_value = ([], 'offline', None)
                broker.get_bars.return_value = ([], 'offline')
                broker.place_option_order.return_value = None
                quotes = Mock()
                quotes.get_option_quote.return_value = dict(symbol='CONTRACT', source_symbol='CONTRACT', bid=2.6, ask=2.7, mid=2.65, bid_date=now.isoformat())
                with ExitStack() as stack:
                    for path, value in [('trading.position_manager.manage.get_user_state', state),
                                        ('trading.position_manager.manage.get_user_risk', SimpleNamespace(ORB_STOP_PCT=.2, STAGE1_ATR_TARGET_MULT=2, STAGE1_TARGET_MIN_PCT=.3)),
                                        ('trading.position_manager.manage.get_user_trade_log', Mock()),
                                        ('trading.position_manager.manage._now_et', now),
                                        ('config.get_settings', {'paper_trading': paper}),
                                        ('trading.trend_profit_exit.partial_remaining', 2),
                                        ('trading.research_order_exit.evaluate_exit', (False, 'hold')),
                                        ('trading.premium_policy.evaluate_position', (True, 'stage1_trend_profit')),
                                        ('trading.position_manager.manage._reconcile_if_phantom', False)]:
                        stack.enter_context(patch(path, return_value=value))
                    for path in ['database.record_paper_option_quote', 'database.log_event', 'config.atomic_update_json', 'trading.position_manager.helpers._snapshot_exit_annotations']:
                        stack.enter_context(patch(path))
                    close = stack.enter_context(patch('trading.position_manager.close._close_position'))
                    _manage_open_position(broker, quotes, trade, 5000)
                    if stop:
                        close.assert_called_once()
                        self.assertEqual('research_or_midpoint_close', close.call_args.args[3])
                        broker.place_option_order.assert_not_called()
                    else:
                        broker.place_option_order.assert_called_once()
                        order = broker.place_option_order.call_args.kwargs
                        self.assertEqual(2, order['qty'])
                        self.assertEqual('sell_to_close', order['position_intent'])
                        self.assertEqual(2.6, order['limit_price'])
                        self.assertEqual('stage1_trend_profit_profit_take', order['order_context']['exit_reason'])
                        self.assertEqual('tradier',order['price_authority'])
                        self.assertEqual('stage1_trend_profit', state['positions'][101]['exit_pending_reason'])
                        close.assert_not_called()
