import hashlib
from contextlib import redirect_stdout
import io
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from trading.diagnostics import native_evidence_report as audit
from trading.diagnostics.orb_evidence import canonical


class EvidenceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'evidence.sqlite3'

    def add(self, table='evaluations', *, account='a', paper=True, payload_account=None,
            ticker='TSLA', sid=None, error=None):
        record = dict(account_digest=account if payload_account is None else payload_account,
                      paper=paper, ticker=ticker, signal=None, error=error)
        if sid is not None:
            record['strategy_id'] = sid
        raw = canonical(record)
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(f'CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY, account_digest TEXT, paper INTEGER, payload BLOB, payload_sha256 TEXT)')
            conn.execute(f'INSERT INTO {table}(account_digest,paper,payload,payload_sha256) VALUES (?,?,?,?)',
                         (account, int(paper), zlib.compress(raw), hashlib.sha256(raw).hexdigest()))
            conn.commit()
        finally:
            conn.close()
        return record

    def read(self):
        return audit.inventory(self.path, account_digest='a', paper=True)

    def test_absent_database_is_not_created_or_verified(self):
        result = self.read()
        self.assertFalse(self.path.exists())
        self.assertEqual(len(result['pairs']), 7)
        self.assertFalse(result['all_pairs_have_replayed_records'])
        self.assertTrue(all(p['status'] == 'no_records' for p in result['pairs'].values()))

    def test_wrong_account_and_mode_are_excluded(self):
        self.add(account='b')
        self.add(paper=False)
        result = self.read()
        self.assertEqual(sum(p['records'] for p in result['pairs'].values()), 0)

    def test_payload_cannot_spoof_scoped_index(self):
        self.add(payload_account='b')
        result = self.read()
        self.assertEqual(result['unassigned_failures']['account_or_mode_mismatch'], 1)
        self.assertFalse(result['all_pairs_have_replayed_records'])

    def test_source_mismatch_does_not_count_as_replayed(self):
        self.add()
        def reject(*args):
            raise ValueError('Evaluator source or pandas version differs; use recorded environment')
        with patch.dict(audit.TABLES, evaluations=('V2_ORB_PULLBACK', reject)):
            result = self.read()
        item = result['pairs']['V2_ORB_PULLBACK:TSLA']
        self.assertEqual(item['replayed'], 0)
        self.assertEqual(item['failures']['recorded_environment_required'], 1)
        self.assertEqual(item['status'], 'replay_failed')

    def test_all_pairs_can_replay_without_claiming_fills_or_coverage(self):
        reverse = {sid: table for table, (sid, _) in audit.TABLES.items() if sid}
        for sid, tickers in audit.PAIRS.items():
            for ticker in tickers:
                self.add(reverse.get(sid, 'bar_evaluations'), ticker=ticker, sid=sid)
        before = self.path.read_bytes()
        def verify(packed, digest, *args):
            return audit.unpack_record(packed, digest)
        with patch.dict(audit.TABLES, {t: (sid, verify) for t, (sid, _) in audit.TABLES.items()}):
            result = self.read()
        self.assertTrue(result['all_pairs_have_replayed_records'])
        self.assertEqual(before, self.path.read_bytes())
        for key in ('continuous_capture_proven', 'option_fills_verified', 'whole_account_replay_complete'):
            self.assertFalse(result[key])

    def test_reproduced_error_is_not_a_clean_pass(self):
        record = self.add(error='ValueError')
        with patch.dict(audit.TABLES, evaluations=('V2_ORB_PULLBACK', lambda *a: record)):
            result = self.read()
        self.assertEqual(result['pairs']['V2_ORB_PULLBACK:TSLA']['status'], 'evaluator_error_reproduced')
        self.assertFalse(result['all_pairs_have_replayed_records'])

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            audit.inventory(self.path, account_digest='a', paper=None)

    def test_cli_incomplete_is_not_a_success_exit(self):
        with redirect_stdout(io.StringIO()):
            code = audit.main([str(self.path), '--account-digest', 'a', '--mode', 'paper'])
        self.assertEqual(code, 2)

    def test_wrong_pair_cannot_fill_expected_slot(self):
        self.add(ticker='SPY')
        result = self.read()
        self.assertEqual(result['unassigned_failures']['native_pair_mismatch'], 1)

    def test_corrupt_compression_cannot_be_verified(self):
        self.add()
        conn = sqlite3.connect(self.path)
        try:
            conn.execute('UPDATE evaluations SET payload=?', (b'not zlib',))
            conn.commit()
        finally:
            conn.close()
        result = self.read()
        self.assertEqual(result['unassigned_failures']['invalid_compressed_record'], 1)
        self.assertFalse(result['all_pairs_have_replayed_records'])


if __name__ == '__main__':
    unittest.main()
