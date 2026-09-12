from datetime import datetime
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

from tests.test_two_leg_execution import _bars, _bearish_bars, ET
from trading.diagnostics import orb_evidence as storage, two_leg_evidence as evidence
from trading.diagnostics.two_leg_replay import verify_record, report
from trading.entry.injected_setups import TWO_LEG, evaluate_injected_setups


class TwoLegEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'orb_decision_evidence.sqlite3'
        for name, value in [('get_current_user_id', 'test-user'), ('get_user_data_dir', Path(self.temp.name))]:
            p = patch.object(evidence, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        self.now = ET.localize(datetime(2026, 8, 12, 10, 3))
        self.bars = _bars()
        self.settings = {'active_broker_account_id': 'private-test-account', 'paper_trading': True}
        self.account = hashlib.sha256(b'private-test-account').hexdigest()

    def evaluate(self, state=None, ticker='TSLA', enabled=True, research_scope=None):
        broker = Mock()
        with patch('trading.entry.injected_setups._now_et', return_value=self.now):
            result = evaluate_injected_setups(state if state is not None else {}, self.bars, ticker,
                {TWO_LEG} if enabled else set(), set() if enabled else {TWO_LEG}, broker,
                self.settings, research_scope=research_scope)
        broker.get_latest_quote.assert_not_called()
        return result

    def records(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute('SELECT payload,payload_sha256 FROM two_leg_evaluations ORDER BY id').fetchall()

    def test_real_signal_and_duplicate_transition_reproduce(self):
        state = {}
        signals, statuses, _ = self.evaluate(state)
        self.assertEqual(statuses[TWO_LEG], 'completed_1m_reclaim')
        self.assertEqual(len(signals), 1)
        self.evaluate(state)
        records = [verify_record(*r) for r in self.records()]
        self.assertEqual([r['status'] for r in records], ['completed_1m_reclaim', 'already_emitted'])
        self.assertNotIn('private-test-account', zlib.decompress(self.records()[0][0]).decode())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_bearish_signal_reproduces(self):
        self.bars = _bearish_bars()
        self.evaluate()
        self.assertEqual(verify_record(*self.records()[0])['signal']['direction'], 'bearish')

    def test_forming_candle_does_not_become_signal(self):
        self.now = ET.localize(datetime(2026, 8, 12, 10, 2))
        self.evaluate()
        record = verify_record(*self.records()[0])
        self.assertIsNone(record['signal'])
        self.assertEqual(record['status'], 'waiting_for_impulse_pullback_reclaim')

    def test_capture_failure_does_not_change_signal(self):
        with patch.object(storage, 'append', side_effect=OSError('disk full')):
            self.assertEqual(len(self.evaluate()[0]), 1)

    def test_input_capture_does_not_retain_mutable_references(self):
        state = {'nested': {'value': 1}}
        payload = evidence.begin(state, self.bars, now=self.now, settings=self.settings)
        state['nested']['value'] = 2
        self.bars.iloc[0, self.bars.columns.get_loc('close')] = 500
        self.assertEqual(payload['state_before']['nested']['value'], 1)
        self.assertEqual(payload['frame']['data'][0][4], 100.)

    def test_research_observation_and_non_native_do_not_record(self):
        self.evaluate(enabled=False)
        self.evaluate(enabled=False, research_scope='research_worker:test')
        self.evaluate(ticker='META')
        self.assertFalse(self.path.exists())

    def test_unknown_identity_and_mode_do_not_record(self):
        with patch.object(evidence, 'get_current_user_id', return_value='system'):
            self.evaluate()
        self.settings['paper_trading'] = None
        self.evaluate()
        self.settings['paper_trading'] = True
        self.settings.pop('active_broker_account_id')
        self.evaluate()
        self.assertFalse(self.path.exists())

    def test_window_does_not_record_all_day(self):
        self.now = ET.localize(datetime(2026, 8, 12, 13))
        self.evaluate()
        self.assertFalse(self.path.exists())

    def test_combined_budget_preserves_both_tables(self):
        self.evaluate()
        original = self.records()
        # An ORB row occupies the same file and therefore the same page budget.
        orb_payload = storage.decode(json.loads(zlib.decompress(original[0][0])))
        storage.append(orb_payload, self.path)
        before = self.path.read_bytes()
        with patch.object(storage, 'MAX_DATABASE_BYTES', self.path.stat().st_size):
            self.evaluate()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.records(), original)
        self.assertFalse(Path(str(self.path) + '-wal').exists())

    def test_invalid_sql_identifier_rejected_before_creating_file(self):
        with self.assertRaises(ValueError): storage.append({}, self.path, table='arbitrary')
        self.assertFalse(self.path.exists())

    def test_payload_budget_does_not_change_signal(self):
        with patch.object(storage, 'MAX_PAYLOAD_BYTES', 10):
            self.assertEqual(len(self.evaluate()[0]), 1)
        self.assertFalse(self.path.exists())

    def test_readonly_report_is_scoped_and_does_not_claim_fills(self):
        self.evaluate()
        before = self.path.read_bytes()
        result = report(self.path, account_digest=self.account, paper=True)
        self.assertEqual(result['verified_evaluations'], 1)
        self.assertFalse(result['option_fills_verified'])
        self.assertFalse(result['whole_account_replay_complete'])
        for account, mode in [(self.account, False), ('another-account', True)]:
            with self.assertRaises(ValueError): report(self.path, account_digest=account, paper=mode)
        self.assertEqual(self.path.read_bytes(), before)

    def test_tamper_and_environment_mismatch_rejected(self):
        self.evaluate()
        packed, digest = self.records()[0]
        with self.assertRaises(ValueError): verify_record(packed, 'bad-hash')
        with patch('trading.diagnostics.two_leg_replay.source_hashes', return_value={}):
            with self.assertRaises(ValueError): verify_record(packed, digest)

    def test_symlink_never_writes_target(self):
        target = Path(self.temp.name) / 'protected'
        target.touch()
        self.path.symlink_to(target)
        self.assertEqual(len(self.evaluate()[0]), 1)
        self.assertEqual(target.stat().st_size, 0)

    def test_actual_evaluator_failure_is_reproduced_not_called_no_setup(self):
        self.bars['time'] = 'invalid timestamp'
        signals, statuses, _ = self.evaluate()
        self.assertEqual(signals, [])
        self.assertEqual(statuses[TWO_LEG], 'data_check_failed')
        result = verify_record(*self.records()[0])
        self.assertEqual(result['status'], 'evaluation_error')
        self.assertIsNotNone(result['error'])

    def test_changed_transition_rejected_even_with_recomputed_checksum(self):
        self.evaluate()
        packed, _ = self.records()[0]
        record = storage.decode(json.loads(zlib.decompress(packed)))
        record['state_after']['emitted'] = False
        raw = storage.canonical(record)
        with self.assertRaises(ValueError):
            verify_record(zlib.compress(raw), hashlib.sha256(raw).hexdigest())

    def test_last_eligible_candle_can_be_recorded_at_1131(self):
        self.now = ET.localize(datetime(2026, 8, 12, 11, 31))
        self.evaluate()
        self.assertEqual(len(self.records()), 1)
        verify_record(*self.records()[0])


if __name__ == '__main__':
    unittest.main()
