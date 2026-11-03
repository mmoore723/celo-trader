import copy
import unittest

from config.research_universe import collection_tickers, filter_research_display, selected_tickers
from strategy_health.research_analytics import build_analytics, build_results_page


class ResearchUniverseTest(unittest.TestCase):
    def test_legacy_and_explicit_empty(self):
        self.assertIsNone(selected_tickers({}))
        self.assertEqual(collection_tickers({}, ['SPY']), ['SPY'])
        self.assertEqual(collection_tickers({'research_tickers': []}, ['SPY']), [])

    def test_focused_research_is_independent_of_daily_shortlist(self):
        settings = {'research_tickers': [' msft ', 'MSFT', 'COIN']}
        self.assertEqual(collection_tickers(settings, ['UVIX', 'SPY']), ['MSFT', 'COIN'])
        self.assertEqual(settings['research_tickers'], [' msft ', 'MSFT', 'COIN'])

    def test_invalid_setting_does_not_silently_broaden_research(self):
        for value in ['SPY', None, [''], [1], ['SPY;QQQ']]:
            with self.assertRaises(ValueError):
                selected_tickers({'research_tickers': value})

    def test_display_filters_before_counts_pagination_and_analytics(self):
        def pair(ticker):
            return dict(ticker=ticker, status='collecting', option_results=1,
                        wins=1, gross_profit=10, gross_loss=0, net_one_contract_pnl=10,
                        profit_factor='infinite', setups=1)
        matrix = dict(target_profit_factor=1.5, ticker_count=2, scanner_source_size=6116,
                      strategies=[dict(strategy_id='ONE', display_name='One',
                                       pairs=[pair('SPY'), pair('UVIX')])])
        original = copy.deepcopy(matrix)
        filtered = filter_research_display(matrix, {'research_tickers': ['SPY']})
        self.assertEqual(matrix, original)
        page = build_results_page(filtered, page=1, page_size=24, result_filter='all')
        self.assertEqual(page['available_tickers'], ['SPY'])
        self.assertEqual(page['ticker_count'], 1)
        self.assertEqual(page['result_counts']['all'], 1)
        self.assertEqual(page['scanner_source_size'], 0)
        self.assertEqual(build_analytics(filtered)['summary']['net_pnl'], 10)

    def test_user_settings_are_isolated_and_do_not_grant_trading(self):
        first = {'research_tickers': ['MSFT'], 'trading_enabled': False}
        second = {'research_tickers': ['QQQ'], 'trading_enabled': True}
        self.assertEqual(collection_tickers(first, []), ['MSFT'])
        self.assertEqual(collection_tickers(second, []), ['QQQ'])
        self.assertFalse(first['trading_enabled'])
        self.assertTrue(second['trading_enabled'])

    def test_worker_exit_capture_is_not_filtered(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        worker = (root/'trading/loop/research_pass.py').read_text()
        self.assertLess(worker.index('capture_authored_exits('), worker.index('for ticker in snapshot["tickers"]'))
        execution = (root/'trading/loop/scan_schedule.py').read_text()
        self.assertNotIn('research_tickers', execution)


if __name__ == '__main__':
    unittest.main()
