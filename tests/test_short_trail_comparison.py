from datetime import datetime
import json
import unittest
from unittest.mock import patch

from research.engine.models import Bar
from database.schema import _init_db_at
from strategy_health.momentum_exit import STRATEGY_ID, PROTOCOL, LOW_WATER_PROTOCOL
from strategy_health.authored_exit_summary import load_authored_exits, authored_summary
from strategy_health.exit_comparison import low_water_comparison
from tests import test_authored_exit_capture as fixtures
from tests.test_momentum_exit_measurement import seed, frame


class ShortTrailComparisonTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.AuthoredExitCaptureTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.frame = frame([
            Bar(datetime(2026, 9, 10, 10, 5), 100, 110, 60, 100),
            Bar(datetime(2026, 9, 10, 10, 10), 100, 100, 80, 81),
            Bar(datetime(2026, 9, 10, 10, 15), 81, 95, 80, 90),
            Bar(datetime(2026, 9, 10, 10, 20), 90, 106, 89, 105),
        ])
        self.f.quote.return_value.update(bid_date="2026-09-10T10:16:00")

    def seed(self, name="short", **kwargs):
        self.f.seed(name, strategy_id=STRATEGY_ID, protocol=PROTOCOL, state=seed(), **kwargs)
        with self.f.connect() as conn:
            row = conn.execute("SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?", (name,)).fetchone()
            meta = {**json.loads(row[0]), "underlying_stop": 105, "underlying_target": 10}
            conn.execute("UPDATE shadow_candidates SET direction='bearish',metadata_json=? WHERE candidate_id=?",
                         (json.dumps(meta), name))

    def variants(self):
        with self.f.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM research_strategy_exit_variants ORDER BY candidate_id")]

    def evidence(self):
        with self.f.connect() as conn:
            exits = load_authored_exits(conn, "a", "2026-09-10")
        return authored_summary([{"candidate_id": k} for k in exits], exits, PROTOCOL)

    def test_separate_latched_decisions_share_entry_and_only_compare_after_both_prices(self):
        self.seed()
        self.f.capture()
        self.assertEqual("collecting", self.f.rows()[0]['status'])
        before = self.variants()
        self.assertEqual("priced", before[0]['status'])
        self.assertEqual("2026-09-10T10:16:00", before[0]['decision_at'])
        comparison = self.evidence()['short_trail_comparison']
        self.assertEqual((0, 1), (comparison['paired_results'], comparison['unpaired']))
        self.assertIsNone(comparison['average_improvement'])
        self.f.now = datetime(2026, 9, 10, 10, 21)
        self.f.quote.return_value.update(bid=.8, bid_date="2026-09-10T10:21:00")
        self.f.capture()
        self.assertEqual("2026-09-10T10:21:00", self.f.rows()[0]['decision_at'])
        self.assertEqual(before, self.variants())
        evidence = self.evidence()
        comparison = evidence['short_trail_comparison']
        self.assertEqual(-123.3, evidence['net_one_contract_pnl'])
        self.assertEqual((1, 1, 0), (comparison['paired_results'], comparison['paired_days'], comparison['unpaired']))
        self.assertEqual(40, comparison['average_improvement'])
        self.assertEqual(40, comparison['median_improvement'])
        self.assertEqual(-83.3, comparison['corrected']['net_pnl'])
        self.assertEqual(0, comparison['corrected']['profit_factor'])
        self.assertEqual(83.3, comparison['corrected']['maximum_drawdown'])
        _init_db_at(self.f.path)
        self.f.capture()
        self.assertEqual(before, self.variants())
        self.assertEqual(2, self.f.quote.call_count)

    def test_only_matching_new_bearish_research_entries_enroll(self):
        self.seed()
        self.seed("other", account="b")
        self.seed("execution", source="execution")
        self.f.seed("long", strategy_id=STRATEGY_ID, protocol=PROTOCOL, state=seed())
        self.f.seed("unstamped", strategy_id=STRATEGY_ID, protocol=None, state=seed())
        self.f.capture()
        self.assertEqual(['short'], [r['candidate_id'] for r in self.variants()])

    def test_forty_overlapping_tests_need_one_quote_when_both_stops_trigger(self):
        for i in range(40):
            self.seed(str(i))
        self.f.frame.loc[5, 'high'] = 106
        self.f.now = datetime(2026, 9, 10, 10, 11)
        self.f.quote.return_value.update(bid_date="2026-09-10T10:11:00")
        self.f.capture()
        self.assertEqual(40, len(self.variants()))
        self.assertTrue(all(r['status'] == 'priced' for r in self.variants() + self.f.rows()))
        self.f.quote.assert_called_once_with('XYZ')
        self.assertEqual(40, self.evidence()['short_trail_comparison']['paired_results'])

    def test_stale_variant_quote_expires_without_replacing_trigger(self):
        self.seed()
        self.f.quote.return_value.update(bid_date="2026-09-10T10:15:59")
        self.f.capture()
        self.assertEqual('pending_quote', self.variants()[0]['status'])
        self.f.now = datetime(2026, 9, 10, 10, 22)
        self.f.capture()
        self.assertEqual('missing_quote', self.variants()[0]['status'])
        self.assertEqual('2026-09-10T10:16:00', self.variants()[0]['decision_at'])
        self.assertEqual(0, self.evidence()['short_trail_comparison']['paired_results'])

    def test_mismatched_or_invalid_counterpart_cannot_improve_results(self):
        self.seed()
        self.f.capture()
        base = {**self.f.rows()[0], 'status': 'priced', 'bid': .8, 'decision_at': '2026-09-10T10:21'}
        variant = self.variants()[0]
        for changes in ({'contract_symbol': 'WRONG'}, {'entry_ask': 1}, {'entry_quote_at': '2026-09-10T10:06'},
                        {'status': 'missing_quote'}, {'bid': float('nan')}, {'candidate_id': 'different'}):
            result = low_water_comparison([{**base, 'low_water_variant': {**variant, **changes}}])
            self.assertEqual(0, result['paired_results'])
            self.assertIsNone(result['average_improvement'])

    def test_matrix_exposes_comparison_without_changing_timer_evidence(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed()
        self.f.capture()
        with patch('database.get_conn', self.f.connect), patch('database._now_et', return_value=self.f.now), patch(
            'config.get_settings', return_value={'active_broker_account_id': 'a', 'research_strategy_ids': [STRATEGY_ID]},
        ), patch('scanner.state_io._read_daily_universe', return_value={}):
            matrix = build_research_matrix()
        strategy = next(s for s in matrix['strategies'] if s['strategy_id'] == STRATEGY_ID)
        pair = next(p for p in strategy['pairs'] if p['ticker'] == 'META')
        self.assertEqual(0, pair['option_results'])
        self.assertEqual(0, pair['authored_exit_evidence']['option_results'])
        self.assertEqual(1, pair['authored_exit_evidence']['short_trail_comparison']['tracked'])
