from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

from config.strategy_catalog import REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids, public_strategy_catalog, reviewed_strategy_integrity_errors
from config.strategy_ticker_recommendations import is_user_authorized_ticker, is_live_enabled_pair
from research.engine.models import Bar
from research.engine.strategies.trend_continuation import TrendContinuation
from strategies import trend_continuation_research_v1 as execution
from strategy_health import trend_exit
from strategy_health.pair_recommendations import assess, decide, recommendations, consent_scope
from tests.test_pair_recommendations import trades
from tests.test_impulse_exit_measurement import candles
from tests.test_momentum_exit_measurement import frame
from tests.test_research_contract_selection import _Tradier
from trading.entry.contract import select_reviewed_v2_contract
from trading.position_manager.manage import _evaluate_reviewed_strategy_exit
from trading.research_contract_selection import select_research_contract
from trading.tested_strategy_research import evaluate_tested_research


SID = 'V2_TREND_CONT'
RULE = REVIEWED_STRATEGIES[SID]


def matrix(ticker='SPY', version='research.1', profile='research_contracts_v1'):
    evidence = assess(trades([20, 20, -10, 20, -10] * 4))
    return {'strategies': [{'strategy_id': SID, 'version': version,
            'display_name': 'Trend Continuation', 'pairs': [{'ticker': ticker,
            'tradable': False, 'research_contract_profile': profile,
            'recommendation': evidence}]}]}, evidence


class TrendResearchExecutionTests(unittest.TestCase):
    def test_integrity_is_current(self):
        self.assertNotIn(SID, reviewed_strategy_integrity_errors())

    def test_approval_authorizes_only_exact_pair_and_preserves_rules_across_modes(self):
        data, evidence = matrix()
        settings = {'paper_trading': True, 'risk_per_trade': .38}
        self.assertTrue(recommendations(data, settings)['recommendations'][0]['can_enable'])
        self.assertNotIn(SID, enabled_reviewed_strategy_ids(settings, ticker='SPY'))
        saved = {**settings, **decide(data, settings, SID, 'SPY', 'enable', evidence['fingerprint'])}
        self.assertEqual(.38, saved['risk_per_trade'])
        for paper in (True, False):
            current = {**saved, 'paper_trading': paper}
            self.assertIn(SID, enabled_reviewed_strategy_ids(current, ticker='SPY'))
            self.assertNotIn(SID, enabled_reviewed_strategy_ids(current, ticker='QQQ'))
            self.assertNotIn(SID, enabled_reviewed_strategy_ids(current, ticker='META'))
            self.assertEqual(not paper, is_live_enabled_pair(SID, 'SPY', current))
            row = next(r for r in public_strategy_catalog(current) if r['strategy_id'] == SID)
            self.assertEqual(['SPY'], row['tickers'])
            self.assertEqual(['SPY'], row['trading_tickers'])
        self.assertFalse(is_user_authorized_ticker(SID, 'SPY', settings))
        self.assertNotIn(SID, enabled_reviewed_strategy_ids({**saved, RULE.setting_key: False}, ticker='SPY'))
        saved['strategy_pair_pauses'][consent_scope(saved, SID, 'SPY')] = True
        self.assertFalse(is_user_authorized_ticker(SID, 'SPY', saved))

    def test_wrong_version_profile_ticker_or_fingerprint_cannot_grant(self):
        for ticker, version, profile in [('SPY', 'research.2', 'research_contracts_v1'),
                                         ('SPY', 'research.1', 'other')]:
            data, evidence = matrix(ticker, version, profile)
            self.assertFalse(recommendations(data, {})['recommendations'][0]['can_enable'])
            with self.assertRaises(ValueError):
                decide(data, {}, SID, ticker, 'enable', evidence['fingerprint'])
        data, _ = matrix()
        with self.assertRaises(ValueError):
            decide(data, {}, SID, 'SPY', 'enable', 'stale')

    def test_endpoint_persists_approval_and_settings_model_keeps_switch(self):
        from api.routes.settings import set_strategy_recommendation_consent, StrategyConsentPayload, get_settings_endpoint, get_strategy_recommendations
        data, evidence = matrix()
        settings = {'paper_trading': True}
        with patch('api.research_snapshot.research_snapshot', return_value=data), \
             patch('config.get_settings', return_value=settings), patch('config.save_settings') as save:
            get_strategy_recommendations()
            self.assertEqual({'ok': True}, set_strategy_recommendation_consent(
                SID, 'SPY', StrategyConsentPayload(decision='enable', fingerprint=evidence['fingerprint'])))
        self.assertTrue(save.call_args.args[0][RULE.setting_key])
        from config.defaults import _DEFAULTS
        with patch('config.get_settings', return_value={**_DEFAULTS, **save.call_args.args[0]}):
            self.assertTrue(getattr(get_settings_endpoint(), RULE.setting_key))

    def test_live_evaluator_matches_research_signal_and_frozen_state_for_both_sides(self):
        start = datetime(2026, 9, 10, 9, 30)
        for sign in (1, -1):
            bars = [Bar(start + timedelta(minutes=5*i), 100+sign*i*.3,
                        100+sign*i*.3+.1, 100+sign*i*.3-.1, 100+sign*i*.3, 500) for i in range(25)]
            now = bars[-1].timestamp + timedelta(minutes=5)
            source = frame(bars)
            with patch.object(execution, '_emitted', set()), patch('trading.tested_strategy_research._emitted', set()):
                research = evaluate_tested_research(source, 'SPY', [SID], scope='research', now=now)
                actual = execution.evaluate(source, 'SPY', execution_scope='one', now=now)
                self.assertEqual(1, len(research))
                self.assertIsNotNone(actual)
                self.assertEqual(research[0].direction, actual.direction)
                self.assertEqual(research[0].trigger_bar, actual.trigger_bar)
                for key in ('underlying_stop', 'underlying_target', 'authored_exit_state', 'authored_exit_protocol', 'strategy_version'):
                    self.assertEqual(research[0].meta[key], actual.meta[key])
                self.assertIsNone(execution.evaluate(source, 'SPY', execution_scope='one', now=now))
                self.assertIsNotNone(execution.evaluate(source, 'SPY', execution_scope='two', now=now))
                self.assertIsNone(execution.evaluate(source, 'SPY', execution_scope='late', now=now+timedelta(minutes=1)))
                self.assertIsNone(execution.evaluate(source, 'META', execution_scope='one', now=now))

    def test_exact_research_contract_selection_and_budget_not_alternate_contract(self):
        broker = _Tradier(['2026-09-11'], {'2026-09-11': [
            {'symbol': 'SPY_NEAR', 'strike': 101, 'bid': 2.95, 'ask': 3., 'spread': .05},
            {'symbol': 'SPY_FAR', 'strike': 102, 'bid': 1.95, 'ask': 2., 'spread': .05}]})
        with patch('trading.research_contract_selection._now_et', return_value=datetime(2026, 9, 10, 11)):
            research, _ = select_research_contract(broker, 'SPY', 'bullish', 100., SID)
            actual, _ = select_reviewed_v2_contract(broker, 'SPY', 'bullish', 100., 400, strategy_id=SID)
            self.assertEqual(research, actual)
            self.assertEqual('SPY_NEAR', actual['symbol'])
            rejected, reason = select_reviewed_v2_contract(broker, 'SPY', 'bullish', 100., 250, strategy_id=SID)
            self.assertIsNone(rejected)
            self.assertEqual('over_budget', reason['reason'])

    def test_dispatch_preserves_completed_bar_stop_target_and_mode_parity(self):
        data = candles()
        entry = datetime(2026, 9, 10, 10, 5, 1)
        for direction, stop, target, column, level in (
            ('bullish', 98, 104, 'low', 97), ('bearish', 104, 98, 'high', 105),
            ('bullish', 98, 104, 'high', 105), ('bearish', 104, 98, 'low', 97)):
            tape = data.copy()
            tape.loc[5, column] = level
            for paper in (True, False):
                trade = {'strategy_id': SID, 'paper': paper, 'direction': direction,
                         'strategy_context_json': json.dumps({'trigger_bar': '2026-09-10T10:05',
                          'underlying_stop': stop, 'underlying_target': target,
                          'authored_exit_state': trend_exit.entry_state(TrendContinuation())})}
                self.assertEqual((False, 'hold'), _evaluate_reviewed_strategy_exit(
                    trade, entry, datetime(2026, 9, 10, 10, 14, 59), one_minute_bars=tape, five_minute_bars=None))
                expected = trend_exit.first_exit(tape, entry_at='2026-09-10T10:05', entry_quote_at=entry,
                    stop=stop, target=target, direction=direction, seed=trend_exit.entry_state(TrendContinuation()),
                    now=datetime(2026, 9, 10, 10, 15))
                self.assertEqual((True, 'trend_cont_'+expected[1]), _evaluate_reviewed_strategy_exit(
                    trade, entry, datetime(2026, 9, 10, 10, 15), one_minute_bars=tape, five_minute_bars=None))

    def test_missing_exit_state_fails_safe_instead_of_switching_exit_policy(self):
        result = _evaluate_reviewed_strategy_exit({'strategy_id': SID}, datetime(2026, 9, 10, 10, 5),
             datetime(2026, 9, 10, 10, 15), one_minute_bars=candles(), five_minute_bars=None)
        self.assertEqual((True, 'trend_cont_invalid_exit_state_safety'), result)
