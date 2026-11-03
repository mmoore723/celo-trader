import unittest
from types import SimpleNamespace
from unittest.mock import patch
from api.daily_brief import trading_tickers


class BriefScopeTests(unittest.TestCase):
    def test_only_exact_enabled_pairs_are_visible(self):
        rules = {'ONE': SimpleNamespace(tickers={'SPY'}, recommendation_tickers={'AMD'})}
        settings = {'watchlist': ['NFLX'], 'research_tickers': ['COIN'],
                    'strategy_pair_approvals': {'grant': {'ticker': 'META'}}}
        with patch('config.strategy_catalog.REVIEWED_STRATEGIES', rules), \
             patch('config.admin_strategy_overrides.tickers', return_value=['NVDA']), \
             patch('config.strategy_catalog.enabled_reviewed_strategy_ids',
                   side_effect=lambda s, ticker: {'ONE'} if ticker in {'SPY','META'} else set()):
            self.assertEqual(['META','SPY'], trading_tickers(settings))

    def test_no_enabled_pairs_does_not_fall_back_to_watchlist(self):
        with patch('config.strategy_catalog.enabled_reviewed_strategy_ids', return_value=set()):
            self.assertEqual([], trading_tickers({'watchlist': ['SPY'], 'research_tickers': ['COIN']}))
