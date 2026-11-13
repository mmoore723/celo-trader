from datetime import datetime, timedelta
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from config.research_order_specs import SPECS
from config.admin_strategy_overrides import updates
from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids, public_strategy_catalog
from strategies import research_orders
from trading.research_order_exit import evaluate_exit, partial_remaining, ATR10
from trading.position_manager.manage import _evaluate_reviewed_strategy_exit, _resolve_latched_exit
from trading.tested_strategy_research import evaluate_tested_research, strategy_details
from strategy_health.exit_protocols import candidate_metadata
from tests.test_impulse_exit_measurement import candles

PAIRS = [('V2_AFTERNOON_COMPRESSION_BREAKOUT', 'SPY'), ('V2_AFTERNOON_COMPRESSION_BREAKOUT', 'QQQ'),
         ('V2_GAP_FILL_RTH', 'AAPL'), ('V2_AFTERNOON_REVERSAL', 'QQQ'), (ATR10, 'SPY'),
         ('V2_SPY_ORB_RSI_MACD_SHORT', 'QQQ'), ('V2_IMPULSE_ANCHORED_VWAP_PULLBACK', 'META'),
         ('V2_IMPULSE_ANCHORED_VWAP_PULLBACK', 'NVDA'), ('RESEARCH_FAILED_RANGE_V2', 'QQQ')]


def position(sid, **meta):
    return dict(id=101, strategy_id=sid, entry_price=2., contracts=4, contract_symbol='CONTRACT',
                broker_account_id='acct', option_type='call', strategy_context_json=json.dumps({
                    'strategy_version': SPECS[sid].version, 'research_order_route': 'exact_research_v1',
                    'trigger_bar': '2026-09-10T10:05', 'direction': 'bullish', **meta}))


class ResearchOrderExecutionTests(unittest.TestCase):
    def test_nine_admin_grants_are_exact_and_mode_independent(self):
        settings = {'paper_trading': True, 'risk_per_trade': .38, 'active_broker_account_id': 'acct'}
        for sid, ticker in PAIRS:
            settings.update(updates(settings, SPECS[sid].source, ticker, SPECS[sid].version, True, 'admin'))
        self.assertTrue(settings['paper_trading'])
        self.assertEqual(.38, settings['risk_per_trade'])
        for paper in (True, False):
            current = {**settings, 'paper_trading': paper}
            for sid, ticker in PAIRS:
                self.assertIn(sid, enabled_reviewed_strategy_ids(current, ticker=ticker))
                self.assertNotIn(sid, enabled_reviewed_strategy_ids(current, ticker='UNAPPROVED'))
                card = next(row for row in public_strategy_catalog(current) if row['strategy_id'] == sid)
                self.assertIn(ticker, card['trading_tickers'])
        sid, ticker = PAIRS[0]
        settings.update(updates(settings, sid, ticker, SPECS[sid].version, False, 'admin'))
        for paper in (True, False):
            self.assertNotIn(sid, enabled_reviewed_strategy_ids({**settings, 'paper_trading': paper}, ticker=ticker))

    def test_wrong_version_unknown_rule_and_loss_pause_rejected(self):
        sid = PAIRS[0][0]
        for source, version, ticker in [(sid, 'wrong', 'SPY'), ('UNKNOWN', 'research.2', 'SPY'), (sid, SPECS[sid].version, '../bad')]:
            with self.assertRaises(ValueError):
                updates({}, source, ticker, version, True, 'admin')
        with patch('strategy_health.closed_trade_guard.is_paused', return_value=True):
            with self.assertRaisesRegex(ValueError, 'closed-trade PF'):
                updates({}, sid, 'SPY', SPECS[sid].version, True, 'admin')

    def test_endpoint_requires_admin_and_does_not_write_on_denial(self):
        from api.routes.settings import set_admin_strategy_override, AdminStrategyOverridePayload
        sid, ticker = PAIRS[0]
        payload = AdminStrategyOverridePayload(strategy_id=sid, ticker=ticker, strategy_version=SPECS[sid].version, enabled=True)
        with patch('config.save_settings') as save:
            with self.assertRaises(HTTPException) as error:
                set_admin_strategy_override(payload, SimpleNamespace(state=SimpleNamespace(is_admin=False)))
            self.assertEqual(403, error.exception.status_code)
            save.assert_not_called()
        with patch('config.get_settings', return_value={'risk_per_trade': .38, 'paper_trading': True}), patch('config.save_settings') as save:
            result = set_admin_strategy_override(payload, SimpleNamespace(state=SimpleNamespace(is_admin=True, user_id='admin')))
            self.assertTrue(result['enabled'])
            self.assertNotIn('risk_per_trade', save.call_args.args[0])
            self.assertNotIn('paper_trading', save.call_args.args[0])

    def test_settings_exposes_every_registered_switch(self):
        from api.routes.settings import get_settings_endpoint
        from config.defaults import _DEFAULTS
        switches = {REVIEWED_STRATEGIES[sid].setting_key: True for sid in SPECS}
        with patch('config.get_settings', return_value={**_DEFAULTS, **switches}):
            settings = get_settings_endpoint().model_dump()
        for key in switches:
            self.assertTrue(settings[key])

    def test_real_compression_and_afternoon_entry_parity(self):
        from tests.test_compression_exit_measurement import setup_bars as compression, frame
        from tests.test_afternoon_exit_measurement import setup_bars as afternoon
        from tests.test_momentum_exit_measurement import frame as five_minute_frame
        for sid, factory, count in [('V2_AFTERNOON_COMPRESSION_BREAKOUT', compression, 226), ('V2_AFTERNOON_REVERSAL', afternoon, 43)]:
            for sign in (1, -1):
                bars = factory(sign, 1)[:count]
                source = frame(bars) if SPECS[sid].timeframe == 1 else five_minute_frame(bars)
                now = bars[-1].timestamp + timedelta(minutes=SPECS[sid].timeframe)
                with patch.object(research_orders, '_emitted', {}), patch('trading.tested_strategy_research._emitted', set()), patch('database.load_scanner_candles', return_value=pd.DataFrame()):
                    expected = evaluate_tested_research(source, 'QQQ', [sid], scope='test', now=now)
                    actual = research_orders.evaluate(source, 'QQQ', execution_scope='order', now=now, strategy_id=sid)
                    self.assertEqual(1, len(expected), sid)
                    self.assertIsNotNone(actual, sid)
                    self.assertEqual(expected[0].direction, actual.direction)
                    self.assertEqual(expected[0].trigger_bar, actual.trigger_bar)
                    for key in ('underlying_stop', 'underlying_target', 'authored_exit_protocol', 'authored_exit_state', 'strategy_version'):
                        self.assertEqual(expected[0].meta[key], actual.meta[key])
                    self.assertIsNone(research_orders.evaluate(source, 'QQQ', execution_scope='order', now=now, strategy_id=sid))
                    self.assertIsNone(research_orders.evaluate(source, 'QQQ', execution_scope='late', now=now+timedelta(minutes=1), strategy_id=sid))

    def test_native_failed_range_alias_preserves_original_and_research_signals(self):
        from tests.test_failed_range_research import OPENING, BREAK, FAIL
        from tests.test_spy_failed_range_recovery_v2 import _frame
        from trading import failed_range_research
        sid = 'RESEARCH_FAILED_RANGE_V2'
        source = _frame(OPENING+[BREAK, FAIL]); now = source.iloc[-1]['time']+timedelta(minutes=1)
        with patch.object(failed_range_research, '_last_trigger', {}), patch.object(research_orders, '_emitted', {}):
            expected = failed_range_research.evaluate(source, ticker='QQQ', scope='research_worker:test', now=now)
            actual = research_orders.evaluate(source, 'QQQ', execution_scope='order', now=now, strategy_id=sid)
        self.assertIsNotNone(actual)
        self.assertEqual(expected.trigger_bar, actual.trigger_bar)
        self.assertEqual(expected.meta['v2_stop'], actual.meta['v2_stop'])
        self.assertEqual('2.1.0', REVIEWED_STRATEGIES[SPECS[sid].source].version)
        self.assertEqual('2.1.0.research.2', actual.meta['strategy_version'])

    def test_gap_rsi_macd_and_impulse_real_entry_parity(self):
        from research.engine.models import Bar
        from tests.test_momentum_exit_measurement import frame
        from tests.test_rsi_macd_exit_measurement import setup_bars
        before, day = datetime(2026, 9, 9, 14, 45), datetime(2026, 9, 10, 9, 30)
        gap = [Bar(before+timedelta(minutes=5*i), 100, 100.4, 99.6, 100) for i in range(15)]
        gap += [Bar(day, 101, 101.2, 100.8, 101), Bar(day+timedelta(minutes=5), 101, 101.25, 98.75, 100.25)]
        impulse = [Bar(day+timedelta(minutes=5*i), 100, 100.1, 99.9, 100, 100) for i in range(15)]
        impulse += [Bar(day+timedelta(minutes=75), 100, 101.1, 100, 101, 100),
                    Bar(day+timedelta(minutes=80), 101, 101.05, 100.7, 100.85, 100),
                    Bar(day+timedelta(minutes=85), 100.85, 101.1, 100.7, 101, 100)]
        for sid, bars, ticker in [('V2_GAP_FILL_RTH', gap, 'AAPL'), ('V2_SPY_ORB_RSI_MACD_SHORT', setup_bars(-1)[:30], 'QQQ'), ('V2_IMPULSE_ANCHORED_VWAP_PULLBACK', impulse, 'META')]:
            tape = frame(bars); now = bars[-1].timestamp+timedelta(minutes=5)
            with patch.object(research_orders, '_emitted', {}), patch('trading.tested_strategy_research._emitted', set()), patch('database.load_scanner_candles', return_value=pd.DataFrame()):
                expected = evaluate_tested_research(tape, ticker, [sid], scope='compare', now=now)
                actual = research_orders.evaluate(tape, ticker, execution_scope='orders', now=now, strategy_id=sid)
            self.assertEqual(1, len(expected), sid)
            self.assertIsNotNone(actual, sid)
            self.assertEqual(expected[0].direction, actual.direction)
            self.assertEqual(expected[0].trigger_bar, actual.trigger_bar)
            if sid == 'V2_IMPULSE_ANCHORED_VWAP_PULLBACK':
                self.assertEqual('captured', actual.meta['structural_levels']['status'])
                self.assertEqual(100, actual.meta['structural_levels']['support'])
                self.assertEqual(expected[0].meta['structural_levels']['support'],
                                 actual.meta['structural_levels']['support'])
            for key in ('underlying_stop', 'underlying_target', 'authored_exit_protocol', 'authored_exit_state'):
                self.assertEqual(expected[0].meta.get(key), actual.meta.get(key), (sid, key))

    def test_all_seven_use_exact_research_contract_selection_with_budget_enforced(self):
        from tests.test_research_contract_selection import _Tradier
        from trading.entry.contract import select_reviewed_v2_contract
        from trading.research_contract_selection import select_research_contract
        broker = _Tradier(['2026-09-11'], {'2026-09-11': [
            {'symbol': 'SPY_NEAR', 'strike': 101, 'bid': 2.95, 'ask': 3., 'spread': .05},
            {'symbol': 'SPY_FAR', 'strike': 102, 'bid': 1.95, 'ask': 2., 'spread': .05}]})
        with patch('trading.research_contract_selection._now_et', return_value=datetime(2026, 9, 10, 11)):
            for sid, spec in SPECS.items():
                expected, _ = select_research_contract(broker, 'SPY', 'bullish', 100, spec.source)
                actual, _ = select_reviewed_v2_contract(broker, 'SPY', 'bullish', 100, 400, strategy_id=sid)
                self.assertEqual(expected, actual)
                if spec.adapter == 'squeeze':
                    # This fixture has only 1 DTE; squeeze requires 3 to 5.
                    self.assertIsNone(actual)
                    continue
                self.assertIsNotNone(actual)
                rejected, reason = select_reviewed_v2_contract(broker, 'SPY', 'bullish', 100, 100, strategy_id=sid)
                self.assertIsNone(rejected)
                self.assertEqual('over_budget', reason['reason'])

    def test_native_atr10_alias_uses_exact_context_entry_and_partial_exit_state(self):
        from tests.test_context_strategy_observers import _nr7_frame
        from strategies import context_strategy_observers as source
        from trading import context_research_entries
        from strategy_health.context_orb_exit import metadata
        frame, _ = _nr7_frame(); now = frame.iloc[-1]['time']+timedelta(minutes=1)
        with patch.object(source, '_atr10_gate', return_value=(True, {'atr10': 2})), patch.object(context_research_entries, '_last_trigger', {}), patch.object(research_orders, '_emitted', {}):
            expected = context_research_entries.evaluate(frame, strategy_id=source.ORB_ATR10_LONG, ticker='SPY', scope='research_worker:test', now=now)
            actual = research_orders.evaluate(frame, 'SPY', execution_scope='order', now=now, strategy_id=ATR10)
        self.assertIsNotNone(actual)
        self.assertEqual(expected.trigger_bar, actual.trigger_bar)
        self.assertEqual(expected.meta['or_midpoint'], actual.meta['or_midpoint'])
        self.assertEqual(metadata(source.ORB_ATR10_LONG)['authored_exit_state'], actual.meta['authored_exit_state'])

    def test_all_library_exits_dispatch_exact_frozen_protocol_in_both_modes(self):
        entry = datetime(2026, 9, 10, 10, 5, 1); now = entry+timedelta(minutes=10)
        for sid, spec in SPECS.items():
            if sid.startswith('RESEARCH_') or strategy_details(spec.source) is None: continue
            strategy = strategy_details(spec.source).factory()
            if spec.source == 'TV_SUPERTREND_REVERSAL_V4':
                strategy._last_timestamp = entry
            meta = candidate_metadata(spec.source, strategy)
            for paper in (True, False):
                trade = {**position(sid, **meta, underlying_stop=98, underlying_target=104), 'paper': paper}
                with patch('trading.research_order_exit.first_exit', return_value=(now, 'underlying_stop')) as engine:
                    result = _evaluate_reviewed_strategy_exit(trade, entry, now, one_minute_bars=candles(), five_minute_bars=None)
                    self.assertEqual((True, 'research_underlying_stop'), result)
                    self.assertEqual(meta['authored_exit_protocol'], engine.call_args.args[0])
                    self.assertEqual(meta.get('authored_exit_state'), engine.call_args.kwargs['meta'].get('authored_exit_state'))

    def test_atr10_partial_target_and_midpoint_full_exit(self):
        from strategy_health.context_orb_exit import metadata
        trade = position(ATR10, **metadata(SPECS[ATR10].source), or_midpoint=98)
        entry = datetime(2026, 9, 10, 10, 5, 1); now = datetime(2026, 9, 10, 10, 8)
        quote = dict(symbol='CONTRACT', source_symbol='CONTRACT', bid=2.6, ask=2.7, bid_date=now.isoformat())
        with patch('trading.research_order_exit.partial_remaining', return_value=2):
            self.assertEqual((True, 'stage1_research_atr10'), evaluate_exit(trade, entry, now, candles(), quote))
            self.assertEqual((True, 'research_atr10_target_100'), evaluate_exit(trade, entry, now, candles(), {**quote, 'bid': 4, 'ask': 4.1}))
            self.assertEqual((False, 'hold'), evaluate_exit(trade, entry, now, candles(), {**quote, 'bid_date': '2026-09-10T10:00'}))
            tape = candles(); tape.loc[1, ['low', 'close']] = [97, 97]
            self.assertEqual((True, 'research_or_midpoint_close'), evaluate_exit(trade, entry, now, tape, quote))
        with patch('trading.research_order_exit.partial_remaining', return_value=0):
            self.assertEqual((False, 'hold'), evaluate_exit(trade, entry, now, candles(), quote))
        pending = {'exit_pending_reason': 'stage1_research_atr10'}
        self.assertEqual((True, 'research_or_midpoint_close'), _resolve_latched_exit(pending, True, 'research_or_midpoint_close', now))
        self.assertEqual((True, 'research_or_midpoint_close'), _resolve_latched_exit(pending, False, 'hold', now))

    def test_partial_quantity_recovery_uses_filled_not_requested_quantity(self):
        from trading.recovery_state import restore_stage1
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE trades(parent_trade_id INTEGER, contracts INTEGER, status TEXT, exit_reason TEXT, broker_account_id TEXT)')
        trade = position(ATR10); trade['contracts'] = 5
        conn.execute("INSERT INTO trades VALUES(101,1,'closed','stage1_research_atr10_profit_take','acct')")
        with patch('database.get_conn', return_value=conn):
            self.assertEqual(2, partial_remaining(trade))
            state = {'exit_pending_reason': 'stage1_research_atr10'}
            restore_stage1(trade, state)
            self.assertFalse(state['stage1_done'])
            conn.execute("INSERT INTO trades VALUES(101,2,'closed','stage1_research_atr10_profit_take','acct')")
            trade['contracts'] = 3
            self.assertEqual(0, partial_remaining(trade))
            restore_stage1(trade, state)
            self.assertTrue(state['stage1_done'])
            self.assertNotIn('exit_pending_reason', state)
        conn.close()

    def test_failed_range_timer_and_session_backstops(self):
        entry = datetime(2026, 9, 10, 10, 5, 1)
        trade = position('RESEARCH_FAILED_RANGE_V2')
        self.assertEqual((False, 'hold'), evaluate_exit(trade, entry, entry+timedelta(minutes=29), None))
        self.assertEqual((True, 'research_failed_range_30m'), evaluate_exit(trade, entry, entry+timedelta(minutes=30), None))
        for sid in SPECS:
            self.assertEqual((True, 'research_session_close'), evaluate_exit(position(sid), entry, entry.replace(hour=16), None))
            self.assertEqual((True, 'research_invalid_exit_state_safety'), evaluate_exit(position(sid, strategy_version='wrong'), entry, entry, candles()))

    def test_position_manager_submits_partial_sell_and_full_sell_in_both_modes(self):
        from contextlib import ExitStack
        from unittest.mock import Mock
        from zoneinfo import ZoneInfo
        from trading.position_manager.manage import _manage_open_position
        from strategy_health.context_orb_exit import metadata
        now = datetime(2026, 9, 10, 10, 8, tzinfo=ZoneInfo('America/New_York'))
        for paper in (True, False):
            for stop in (False, True):
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
                                        ('trading.research_order_exit.partial_remaining', 2),
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
                        self.assertEqual('stage1_research_atr10_profit_take', order['order_context']['exit_reason'])
                        self.assertEqual('stage1_research_atr10', state['positions'][101]['exit_pending_reason'])
                        close.assert_not_called()
