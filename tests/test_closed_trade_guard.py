import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from strategy_health.closed_trade_guard import enforce, is_paused, scope
from config.strategy_catalog import REVIEWED_STRATEGIES
from config.strategy_ticker_recommendations import is_user_authorized_ticker

SID = 'V2_SPY_TREND_CONT'
VERSION = REVIEWED_STRATEGIES[SID].version


class ClosedTradeGuardTests(unittest.TestCase):
    def test_only_completed_losing_account_pair_version_is_paused(self):
        settings = {'active_broker_account_id': 'acct', 'paper_trading': True, 'risk_per_trade': .38}
        pair = dict(ticker='SPY', completed_trades=20, gross_profit=30, gross_loss=70, profit_factor=.43, realized_pnl=-40)
        evidence = {'available': True, 'strategies': [{'strategy_id': SID, 'version': VERSION, 'pairs': [pair]}]}
        with tempfile.TemporaryDirectory() as folder, \
             patch('config.get_user_data_dir', return_value=Path(folder)), \
             patch('config.get_settings', side_effect=lambda: dict(settings)), \
             patch('strategy_health.closed_trade_evidence.build_closed_trade_evidence', return_value=evidence), \
             patch('config.save_settings', side_effect=lambda update: settings.update(update)) as save:
            self.assertEqual([scope(settings, SID, 'SPY', VERSION)], enforce())
            self.assertTrue(is_paused(settings, SID, 'SPY', VERSION))
            self.assertFalse(is_paused({**settings, 'paper_trading': False}, SID, 'SPY', VERSION))
            self.assertFalse(is_paused({**settings, 'active_broker_account_id': 'other'}, SID, 'SPY', VERSION))
            self.assertFalse(is_paused(settings, SID, 'QQQ', VERSION))
            self.assertFalse(is_paused(settings, SID, 'SPY', 'new-version'))
            self.assertFalse(is_user_authorized_ticker(SID, 'SPY', settings))
            self.assertEqual([], enforce())
            save.assert_called_once()
            self.assertEqual({'strategy_closed_trade_pauses'}, set(save.call_args.args[0]))
            self.assertEqual(.38, settings['risk_per_trade'])

    def test_empty_winning_breakeven_or_invalid_data_cannot_pause(self):
        settings = {'active_broker_account_id': 'acct', 'paper_trading': True}
        for completed, gains, losses in [(0, 0, 20), (1, 0, 20), (19, 0, 20), (20, 20, 0), (20, 20, 20), (20, float('nan'), 20), (20, None, 20), (None, 0, 20)]:
            pair = dict(ticker='SPY', completed_trades=completed, gross_profit=gains, gross_loss=losses)
            evidence = {'available': True, 'strategies': [{'strategy_id': SID, 'version': VERSION, 'pairs': [pair]}]}
            with tempfile.TemporaryDirectory() as folder, \
                 patch('config.get_user_data_dir', return_value=Path(folder)), \
                 patch('config.get_settings', return_value=settings), \
                 patch('strategy_health.closed_trade_evidence.build_closed_trade_evidence', return_value=evidence), \
                 patch('config.save_settings') as save:
                self.assertEqual([], enforce())
                save.assert_not_called()

    def test_no_account_does_not_read_journal(self):
        with patch('config.get_settings', return_value={}), \
             patch('strategy_health.closed_trade_evidence.build_closed_trade_evidence') as build:
            self.assertEqual([], enforce())
            build.assert_not_called()
