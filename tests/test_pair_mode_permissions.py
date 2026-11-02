"""Permission unit tests. Mocked integrity is not deployment certification."""
import unittest
from unittest.mock import patch
from config.admin_strategy_overrides import updates, active
from config.strategy_catalog import REVIEWED_STRATEGIES
from config.strategy_ticker_recommendations import is_user_authorized_ticker


class PairModePermissionsTests(unittest.TestCase):
    @patch('config.strategy_catalog.reviewed_strategy_integrity_errors', return_value={})
    @patch('strategy_health.closed_trade_guard.is_paused', return_value=False)
    def test_pair_permission_is_shared_without_switching_account_mode(self, *_):
        checked = 0
        for sid, rule in REVIEWED_STRATEGIES.items():
            tickers = rule.tickers | rule.recommendation_tickers
            if rule.observation_only or not tickers:
                continue
            ticker = sorted(tickers)[0]
            settings = {'paper_trading': True, 'active_broker_account_id': 'paper-account', 'risk_per_trade': .02}
            changes = updates(settings, sid, ticker, rule.version, True, 'admin')
            self.assertNotIn('paper_trading', changes)
            self.assertNotIn('active_broker_account_id', changes)
            self.assertNotIn('risk_per_trade', changes)
            current = {**settings, **changes}
            for mode, account in [(True, 'paper-account'), (False, 'live-account')]:
                scoped = {**current, 'paper_trading': mode, 'active_broker_account_id': account}
                self.assertTrue(active(scoped, sid, ticker), (sid, mode))
                self.assertTrue(is_user_authorized_ticker(sid, ticker, scoped), (sid, mode))
            checked += 1
        self.assertGreater(checked, 0)

    @patch('config.strategy_catalog.reviewed_strategy_integrity_errors', return_value={})
    def test_shared_permission_does_not_clear_live_safety_pause(self, *_):
        sid = 'V2_SPY_TREND_CONT'
        rule = REVIEWED_STRATEGIES[sid]
        with patch('strategy_health.closed_trade_guard.is_paused', return_value=False):
            settings = {'paper_trading': True}
            settings.update(updates(settings, sid, 'SPY', rule.version, True, 'admin'))
        with patch('strategy_health.closed_trade_guard.is_paused', return_value=True):
            self.assertFalse(is_user_authorized_ticker(sid, 'SPY', {**settings, 'paper_trading': False}))


if __name__ == '__main__':
    unittest.main()
