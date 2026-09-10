from datetime import datetime
import json
import unittest
from unittest.mock import patch

from database.schema import _init_db_at
from strategy_health import gap_fill_exit, momentum_exit
from strategy_health.authored_exit_summary import authored_summary, load_authored_exits
from tests import test_short_trail_comparison as fixtures
from tests.test_gap_fill_exit_measurement import seed


class GapFillExitCaptureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ShortTrailComparisonTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f

    def seed(self, name='gap', **kwargs):
        self.f.seed(name, strategy_id=gap_fill_exit.STRATEGY_ID, protocol=gap_fill_exit.PROTOCOL, state=seed(), **kwargs)
        with self.f.connect() as conn:
            meta = json.loads(conn.execute('SELECT metadata_json FROM shadow_candidates WHERE candidate_id=?', (name,)).fetchone()[0])
            meta.update(underlying_stop=105, underlying_target=10)
            conn.execute("UPDATE shadow_candidates SET direction='bearish',metadata_json=? WHERE candidate_id=?",
                         (json.dumps(meta), name))

    def summaries(self):
        with self.f.connect() as conn:
            exits = load_authored_exits(conn, 'a', '2026-09-10')
        samples = [{'candidate_id': k} for k in exits]
        return {module.STRATEGY_ID: authored_summary(samples, exits, module.PROTOCOL)
                for module in (gap_fill_exit, momentum_exit)}

    def test_simultaneous_gap_and_momentum_exits_never_mix_evidence(self):
        self.seed()
        self.fixture.seed('momentum')
        self.f.capture()
        before = self.fixture.variants()
        self.assertEqual(2, len(before))
        self.assertTrue(all(r['status'] == 'priced' for r in before))
        self.f.quote.assert_called_once_with('XYZ')
        for summary in self.summaries().values():
            self.assertEqual(1, summary['tracked'])
            self.assertEqual(0, summary['option_results'])
            self.assertEqual(1, summary['short_trail_comparison']['unpaired'])
        self.f.now = datetime(2026, 9, 10, 10, 21)
        self.f.quote.return_value.update(bid=.8, bid_date='2026-09-10T10:21:00')
        self.f.capture()
        _init_db_at(self.f.path)
        self.f.capture()
        self.assertEqual(before, self.fixture.variants())
        for module in (gap_fill_exit, momentum_exit):
            summary = self.summaries()[module.STRATEGY_ID]
            self.assertEqual(1, summary['option_results'])
            comparison = summary['short_trail_comparison']
            self.assertEqual(module.LOW_WATER_PROTOCOL, comparison['protocol'])
            self.assertEqual(1, comparison['paired_results'])
            self.assertEqual(40, comparison['average_improvement'])
            self.assertEqual(0, comparison['corrected']['profit_factor'])
        self.assertEqual(2, self.f.quote.call_count)

    def test_wrong_account_source_or_protocol_does_not_enroll(self):
        self.seed()
        self.seed('other', account='b')
        self.seed('execution', source='execution')
        self.f.seed('wrong-protocol', strategy_id=gap_fill_exit.STRATEGY_ID,
                    protocol=momentum_exit.PROTOCOL, state=seed())
        self.f.capture()
        self.assertEqual(['gap'], [r['candidate_id'] for r in self.fixture.variants()])

    def test_forty_gap_plays_all_collect_without_cooldown(self):
        for i in range(40):
            self.seed(str(i))
        self.f.frame.loc[5, 'high'] = 106
        self.f.now = datetime(2026, 9, 10, 10, 11)
        self.f.quote.return_value.update(bid_date='2026-09-10T10:11:00')
        self.f.capture()
        self.assertEqual(40, len(self.fixture.variants()))
        self.assertTrue(all(r['status'] == 'priced' for r in self.fixture.variants()))
        summary = self.summaries()[gap_fill_exit.STRATEGY_ID]
        self.assertEqual(40, summary['short_trail_comparison']['paired_results'])
        self.f.quote.assert_called_once_with('XYZ')

    def test_other_strategy_variant_cannot_override_the_matching_one(self):
        self.seed()
        self.f.capture()
        with self.f.connect() as conn:
            conn.execute("""INSERT INTO research_strategy_exit_variants
                (candidate_id,protocol,contract_symbol,entry_ask,entry_quote_at,status,bid,decision_at)
                VALUES ('gap',?,'XYZ',2,'2026-09-10T10:05:03','priced',1000,'2026-09-10T10:16')""",
                         (momentum_exit.LOW_WATER_PROTOCOL,))
        comparison = self.summaries()[gap_fill_exit.STRATEGY_ID]['short_trail_comparison']
        self.assertEqual(1, comparison['tracked'])
        self.assertEqual(0, comparison['paired_results'])
        self.assertIsNone(comparison['corrected']['net_pnl'])

    def test_matrix_exposes_gap_comparison_and_retains_original_timer_fields(self):
        from strategy_health.research_matrix import build_research_matrix
        self.seed()
        self.f.capture()
        with patch('database.get_conn', self.f.connect), patch('database._now_et', return_value=self.f.now), patch(
            'config.get_settings', return_value={'active_broker_account_id': 'a', 'research_strategy_ids': [gap_fill_exit.STRATEGY_ID]},
        ), patch('scanner.state_io._read_daily_universe', return_value={}):
            matrix = build_research_matrix()
        strategy = next(s for s in matrix['strategies'] if s['strategy_id'] == gap_fill_exit.STRATEGY_ID)
        self.assertTrue(strategy['exit_measurement']['authored_collector_enabled'])
        pair = next(p for p in strategy['pairs'] if p['ticker'] == 'META')
        self.assertEqual(0, pair['option_results'])
        self.assertEqual(0, pair['authored_exit_evidence']['option_results'])
        self.assertEqual(1, pair['authored_exit_evidence']['short_trail_comparison']['tracked'])
