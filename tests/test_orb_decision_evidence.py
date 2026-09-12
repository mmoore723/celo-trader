from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

from trading.diagnostics import orb_evidence as evidence
from trading.entry.injected_setups import ORB, evaluate_injected_setups
from tests.test_orb_retouch_execution import frame
from trading.diagnostics.orb_replay import verify_record


class OrbEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'orb_decision_evidence.sqlite3'
        for target, value in [('trading.diagnostics.orb_evidence.get_current_user_id', 'test-user'),
                              ('trading.diagnostics.orb_evidence.get_user_data_dir', Path(self.temp.name))]:
            p = patch(target, return_value=value)
            p.start(); self.addCleanup(p.stop)
        self.bars = frame([100.] * 15 + [101.], [100.5] * 15 + [101.2], [99.5] * 15 + [100.8])
        self.now = datetime(2026, 1, 2, 9, 47)
        self.settings = {'active_broker_account_id': 'private-test-account', 'paper_trading': True}

    def evaluate(self, state=None, price=100.53, enabled=True, research_scope=None):
        quote = {'bp': price-.01, 'ap': price+.01, 't': '2026-01-02T14:47:00+00:00'}
        with patch('trading.entry.injected_setups._now_et', return_value=self.now), \
             patch('trading.entry.injected_setups.record_underlying_quote'):
            return evaluate_injected_setups(state if state is not None else {}, self.bars, 'TSLA',
                {ORB} if enabled else set(), set() if enabled else {ORB},
                Mock(get_latest_quote=Mock(return_value=quote)), self.settings, research_scope=research_scope)

    def records(self):
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute('SELECT payload,payload_sha256 FROM evaluations ORDER BY id').fetchall()
        finally:
            conn.close()

    def test_real_signal_state_and_inputs_reproduce(self):
        signals, statuses, _ = self.evaluate()
        record = verify_record(*self.records()[0])
        self.assertEqual('first_retouch_quote', statuses[ORB])
        self.assertEqual(1, len(signals))
        self.assertEqual('emitted', record['state_after']['terminal'])
        self.assertNotIn('private-test-account', zlib.decompress(self.records()[0][0]).decode())
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_armed_then_emitted_then_terminal_reproduce(self):
        state = {}
        self.evaluate(state, price=101.)
        self.evaluate(state)
        self.evaluate(state)
        self.assertEqual(['armed_waiting_for_first_retouch', 'first_retouch_quote', 'emitted'],
                         [verify_record(*row)['status'] for row in self.records()])

    def test_input_copy_survives_later_mutation(self):
        state = {'key': 'before'}
        payload = evidence.begin(state, self.bars, now=self.now, price=101, quote={}, settings=self.settings)
        state['key'] = 'after'
        self.bars.iloc[0, self.bars.columns.get_loc('close')] = 500
        self.assertEqual('before', payload['state_before']['key'])
        self.assertEqual(100, payload['frame']['data'][0][4])
        self.assertIsNone(payload['quote']['t'])

    def test_capture_errors_do_not_suppress_signal(self):
        with patch.object(evidence, 'append', side_effect=OSError('disk full')):
            signals, statuses, _ = self.evaluate()
        self.assertEqual(1, len(signals))
        self.assertEqual('first_retouch_quote', statuses[ORB])

    def test_system_context_and_unknown_account_do_not_capture(self):
        with patch.object(evidence, 'get_current_user_id', return_value='system'):
            self.evaluate()
        self.settings.pop('active_broker_account_id')
        self.evaluate()
        self.assertFalse(self.path.exists())

    def test_research_and_observe_only_never_write_execution_evidence(self):
        self.evaluate(enabled=False)
        self.evaluate(enabled=False, research_scope='research_worker:test')
        self.assertFalse(self.path.exists())

    def test_outside_window_does_not_keep_recording(self):
        self.now = datetime(2026, 1, 2, 11)
        self.evaluate()
        self.assertFalse(self.path.exists())

    def test_cap_stops_capture_without_deleting_existing_records(self):
        self.evaluate()
        original = self.records()
        with patch.object(evidence, 'MAX_DATABASE_BYTES', self.path.stat().st_size):
            self.evaluate()
        self.assertEqual(original, self.records())

    def test_nonfinite_metadata_roundtrips_without_silent_zero(self):
        self.bars['rvol'] = float('nan')
        self.evaluate()
        verify_record(*self.records()[0])

    def test_evaluator_error_is_recorded_without_becoming_a_signal(self):
        self.bars['high'] = 1
        signals, statuses, _ = self.evaluate()
        self.assertEqual([], signals)
        self.assertEqual('data_check_failed', statuses[ORB])
        self.assertEqual('ValueError', verify_record(*self.records()[0])['error'])

    def test_payload_budget_failure_does_not_change_signal(self):
        with patch.object(evidence, 'MAX_PAYLOAD_BYTES', 10):
            signals, _, _ = self.evaluate()
        self.assertEqual(1, len(signals))
        self.assertFalse(self.path.exists())

    def test_unknown_mode_is_not_assumed_to_be_paper(self):
        self.settings.pop('paper_trading')
        self.evaluate()
        self.assertEqual([], self.records())

    def test_account_and_mode_remain_separate_inside_shared_user_file(self):
        self.evaluate()
        self.settings['paper_trading'] = False
        self.evaluate()
        self.settings['active_broker_account_id'] = 'second-account'
        self.evaluate()
        rows = [verify_record(*r) for r in self.records()]
        self.assertEqual([True, False, False], [r['paper'] for r in rows])
        self.assertEqual(rows[0]['account_digest'], rows[1]['account_digest'])
        self.assertNotEqual(rows[1]['account_digest'], rows[2]['account_digest'])

    def test_database_lock_does_not_change_signal(self):
        self.evaluate()
        conn = sqlite3.connect(self.path)
        try:
            conn.execute('BEGIN EXCLUSIVE')
            signals, _, _ = self.evaluate()
            self.assertEqual(1, len(signals))
        finally:
            conn.rollback()
            conn.close()
        self.assertEqual(1, len(self.records()))

    def test_forming_candle_is_retained_but_cannot_arm_breakout(self):
        self.now = datetime(2026, 1, 2, 9, 45, 20)
        self.evaluate()
        record = verify_record(*self.records()[0])
        self.assertEqual(16, len(record['frame']['data']))
        self.assertEqual('building_or_waiting_for_breakout', record['status'])

    def test_tampered_hash_or_decision_is_rejected(self):
        self.evaluate()
        packed, digest = self.records()[0]
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            verify_record(packed, 'wrong')
        data = json.loads(zlib.decompress(packed))
        data['status'] = 'fake'
        raw = evidence.canonical(data)
        with self.assertRaisesRegex(ValueError, 'does not reproduce'):
            verify_record(zlib.compress(raw), hashlib.sha256(raw).hexdigest())

    def test_source_change_is_not_silently_replayed(self):
        self.evaluate()
        with patch('trading.diagnostics.orb_replay.source_hashes', return_value={}):
            with self.assertRaisesRegex(ValueError, 'differs'):
                verify_record(*self.records()[0])

    def test_symlink_is_rejected_without_touching_target(self):
        target = Path(self.temp.name) / 'target'
        target.touch()
        self.path.symlink_to(target)
        signals, _, _ = self.evaluate()
        self.assertEqual(0, target.stat().st_size)
        self.assertEqual(1, len(signals))


if __name__ == '__main__':
    unittest.main()
