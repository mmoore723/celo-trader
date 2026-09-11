from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from strategy_health.expiration_study_summary import summary, metrics
from strategy_health.expiration_study_exits import PROTOCOL_BY_STRATEGY
from strategy_health.impulse_exit import STRATEGY_ID
from trading.expiration_study_selection import PROFILE
from tests import test_expiration_study_worker as fixtures


def sample(name, contract='PRIMARY'):
    return dict(candidate_id=name, ticker='META', observed_at='2026-09-10T10:00:01',
                metadata_json=json.dumps({'strategy_version': 'research.1'}), entry_contract=contract)


def study(name, bid=2.5, **changes):
    state = dict(status='priced', profile_version=PROFILE, strategy_id=STRATEGY_ID,
                 protocol=PROTOCOL_BY_STRATEGY[STRATEGY_ID], strategy_version='research.1',
                 contract_symbol='META260918C00101000', entry_ask=2,
                 entry_quote_at='2026-09-10T10:00:03', bid=bid, bid_at='2026-09-10T10:30:03')
    state.update(changes)
    return dict(candidate_id=name, ticker='META', state=state, selection={'reason': 'selected'})


class ExpirationSummaryTests(unittest.TestCase):
    def test_missing_primary_contract_and_missing_exit_are_different_cohorts(self):
        samples = [sample('matched'), sample('only', None), sample('pending'), sample('missing')]
        studies = {name: study(name) for name in ('matched', 'only', 'pending', 'missing')}
        studies['missing']['state']['status'] = 'missing_quote'
        primary = [dict(id='matched', pnl=-10, entry_at='2026-09-10T10:00:01', exit_at='2026-09-10T10:35:00')]
        before = deepcopy((samples, studies, primary))
        result = summary(samples, studies, STRATEGY_ID, primary)
        self.assertEqual(4, result['setups'])
        self.assertEqual(3, result['completed']['option_results'])
        self.assertEqual(1, result['matched']['results'])
        self.assertEqual(1, result['longer_only']['option_results'])
        self.assertEqual(1, result['primary_incomplete'])
        self.assertEqual(56.7, result['matched']['average_change'])
        self.assertFalse(result['recommendation_eligible'])
        self.assertEqual(before, (samples, studies, primary))

    def test_empty_or_missing_prices_are_not_zero_profit(self):
        self.assertIsNone(summary([], {}, STRATEGY_ID, []))
        result = summary([sample('x')], {'x': study('x', status='pending_quote')}, STRATEGY_ID, [])
        self.assertEqual(0, result['completed']['option_results'])
        self.assertIsNone(result['completed']['net_one_contract_pnl'])
        self.assertIsNone(result['completed']['profit_factor'])
        self.assertEqual(0, result['matched']['results'])

    def test_wrong_version_protocol_ticker_and_profile_are_excluded(self):
        for key, value in (('strategy_version', 'old'), ('protocol', 'wrong'),
                           ('profile_version', 'wrong'), ('strategy_id', 'wrong')):
            row = study('x', **{key: value})
            result = summary([sample('x')], {'x': row}, STRATEGY_ID, [])
            self.assertEqual(1, result['rejected_identity'])
            self.assertEqual(0, result['completed']['option_results'])
        row = study('x'); row['ticker'] = 'AAPL'
        self.assertEqual(1, summary([sample('x')], {'x': row}, STRATEGY_ID, [])['rejected_identity'])

    def test_overlapping_matched_positions_use_both_exit_times(self):
        samples = [sample('a'), sample('b')]
        studies = {'a': study('a'), 'b': study('b', entry_quote_at='2026-09-10T10:31:00', bid_at='2026-09-10T10:40:00')}
        primary = [dict(id='a', pnl=-20, entry_at='2026-09-10T10:00:01', exit_at='2026-09-10T10:35:00'),
                   dict(id='b', pnl=-20, entry_at='2026-09-10T10:31:00', exit_at='2026-09-10T10:40:00')]
        result = summary(samples, studies, STRATEGY_ID, primary)
        self.assertEqual(2, result['matched']['results'])
        self.assertEqual(2, result['non_overlapping']['option_results'])
        self.assertEqual(1, result['matched_non_overlapping']['results'])

    def test_drawdown_uses_closed_time_batches_not_input_order(self):
        rows = [dict(pnl=-30, exit_at='2026-09-10T11:00:00'),
                dict(pnl=20, exit_at='2026-09-10T10:30:00'),
                dict(pnl=5, exit_at='2026-09-10T11:00:00')]
        result = metrics(rows)
        self.assertEqual(25, result['maximum_drawdown_one_contract'])
        self.assertEqual(-5, result['net_one_contract_pnl'])
        self.assertEqual(.83, result['profit_factor'])
        self.assertEqual(5, result['median_one_contract_pnl'])
        self.assertEqual(-1.67, result['average_one_contract_pnl'])

    def test_study_cannot_change_primary_matrix_metrics_or_recommendations(self):
        from strategy_health.research_matrix import build_research_matrix
        from strategy_health.pair_recommendations import recommendations
        f = fixtures.ExpirationWorkerTests(); f.setUp()
        self.addCleanup(f.doCleanups)
        f.fixture.capture()
        settings = {**f.settings, 'research_strategy_ids': [f.signal.strategy_id]}
        with patch('database.get_conn', f.fixture.connect), patch('database._now_et', return_value=f.fixture.now), patch(
                'config.get_settings', return_value=settings), patch('scanner.state_io._read_daily_universe', return_value={}):
            before = build_research_matrix()
            f.test_real_authored_exit_is_captured_without_mutating_primary_result()
            after = build_research_matrix()
            self.assertEqual(recommendations(before, settings), recommendations(after, settings))
            comparisons = [p['expiration_study'] for s in after['strategies'] for p in s['pairs'] if p['expiration_study']]
            self.assertEqual(1, len(comparisons))
            self.assertEqual(1, comparisons[0]['matched']['results'])
            for matrix in (before, after):
                for strategy in matrix['strategies']:
                    for pair in strategy['pairs']:
                        pair.pop('expiration_study')
            self.assertEqual(before, after)
        with f.fixture.connect() as conn:
            from database.expiration_study import load
            self.assertEqual([], load(conn, account='a', cutoff=(f.fixture.now+timedelta(days=1)).isoformat()))


if __name__ == '__main__':
    unittest.main()
