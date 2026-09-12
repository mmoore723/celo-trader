from contextlib import closing
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

import pandas as pd

from tests.test_context_strategy_observers import _vwap_displacement_frame
from tests.test_spy_failed_range_recovery_v2 import _frame
from trading.diagnostics import bar_evidence as evidence, orb_evidence as storage
from trading.diagnostics.bar_replay import report, verify_record
from strategies.market_structure import Side

TREND, FVG, RECOVERY, DISPLACEMENT = tuple(evidence.SPECS)


def five_minute_frame(buckets):
    rows = []
    start = pd.Timestamp('2026-08-10 09:30')
    for index, (op, high, low, close) in enumerate(buckets):
        for minute in range(5):
            rows.append(dict(time=start + pd.Timedelta(minutes=5*index+minute),
                             open=op, high=high, low=low, close=close, volume=100., rvol=1.4))
    return pd.DataFrame(rows)


class BarEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / 'orb_decision_evidence.sqlite3'
        self.settings = dict(active_broker_account_id='private-account', paper_trading=True)
        self.account = hashlib.sha256(b'private-account').hexdigest()
        self.recorder = evidence.Recorder(self.settings)
        for name, value in [('get_current_user_id', 'test-user'), ('get_user_data_dir', self.folder)]:
            p = patch.object(evidence, name, return_value=value); p.start(); self.addCleanup(p.stop)
        for spec in evidence.SPECS.values():
            module = importlib.import_module(spec[0])
            for name in spec[3]:
                original = getattr(module, name)
                p = patch.object(module, name, {} if isinstance(original, dict) else set())
                p.start(); self.addCleanup(p.stop)

    def capture(self, sid, frame, now, ticker='SPY', end=None):
        spec = evidence.SPECS[sid]
        module = importlib.import_module(spec[0]); fn = getattr(module, spec[1])
        now = pd.Timestamp(now)
        if now.tzinfo is None: now = now.tz_localize('America/New_York')
        with patch.object(evidence, 'clock', side_effect=[now, end or now]):
            ticket = self.recorder.begin(sid, frame, ticker, fn)
            # Freeze only in tests so the real untouched evaluator uses the
            # same clock as the capture. Replay itself never patches modules.
            with patch.object(pd.Timestamp, 'now', return_value=now):
                try:
                    signal = fn(frame, ticker=ticker, execution_scope='test-user')
                except Exception as exc:
                    self.recorder.finish(ticket, None, error=type(exc).__name__)
                    return None
            self.recorder.finish(ticket, signal)
        return signal

    def rows(self):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute('SELECT payload,payload_sha256 FROM bar_evaluations ORDER BY id').fetchall()

    def blob(self, digest):
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute('SELECT payload FROM input_blobs WHERE digest=?', (digest,)).fetchone()
            if row is None: raise ValueError('Missing blob')
            return row[0]

    def verify(self):
        return [verify_record(p, h, self.blob) for p, h in self.rows()]

    def recovery_frame(self):
        return _frame([(100., 101., 99., 100.)]*15 +
                      [(101., 101.4, 100.9, 101.2), (101.3, 101.3, 100.8, 100.9)])

    def test_recovery_signal_and_duplicate_reproduce_without_global_mutation(self):
        frame = self.recovery_frame()
        first = self.capture(RECOVERY, frame, '2026-08-10 09:47')
        self.assertIsNotNone(first)
        self.assertIsNone(self.capture(RECOVERY, frame, '2026-08-10 09:47'))
        module = importlib.import_module(evidence.SPECS[RECOVERY][0])
        before = deepcopy(module._emitted_trigger_by_session)
        records = self.verify()
        self.assertEqual([r['signal'] is not None for r in records], [True, False])
        self.assertEqual(module._emitted_trigger_by_session, before)
        self.assertNotIn('private-account', zlib.decompress(self.rows()[0][0]).decode())
        self.assertNotIn('test-user', zlib.decompress(self.rows()[0][0]).decode())

    def test_displacement_reproduces_for_both_native_tickers_with_history(self):
        frame, now = _vwap_displacement_frame()
        for ticker in ('TSLA', 'AMZN'):
            self.assertIsNotNone(self.capture(DISPLACEMENT, frame, now, ticker=ticker))
            self.assertIsNone(self.capture(DISPLACEMENT, frame, now, ticker=ticker))
        self.assertEqual(len(self.verify()), 4)
        with closing(sqlite3.connect(self.path)) as conn:
            # All four evaluations share a single frame and one history chunk.
            self.assertEqual(conn.execute('SELECT count(*) FROM input_blobs').fetchone()[0], 2)

    def test_fvg_actual_signal_reproduces(self):
        frame = five_minute_frame([(100., 100.2, 99.8, 100.)]*46 +
            [(104.,104.2,103.8,104.), (104.,107.,104.,106.5),
             (107.,107.4,106.8,107.1), (107.1,107.2,106.7,107.)])
        self.assertIsNotNone(self.capture(FVG, frame, '2026-08-10 13:40'))
        self.assertIsNone(self.capture(FVG, frame, '2026-08-10 13:40'))
        self.assertEqual(len(self.verify()), 2)

    def test_trend_breakout_state_reproduces_and_foreign_user_is_excluded(self):
        frame = five_minute_frame([(100+i*.1,100.2+i*.1,99.8+i*.1,100+i*.1) for i in range(24)]
                                 + [(102.4,104.5,102.2,104.3)])
        module = importlib.import_module(evidence.SPECS[TREND][0])
        key = ('test-user', 'SPY', '2026-08-10')
        module._active_breakout_by_session[key] = (Side.LONG, 200.)
        module._active_breakout_by_session[('another-user','SPY','2026-08-10')] = (Side.SHORT, 50.)
        self.assertIsNotNone(self.capture(TREND, frame, '2026-08-10 11:35'))
        self.assertIsNone(self.capture(TREND, frame, '2026-08-10 11:35'))
        before = deepcopy(module._active_breakout_by_session)
        self.verify()
        self.assertEqual(module._active_breakout_by_session, before)
        self.assertNotIn('another-user', zlib.decompress(self.rows()[0][0]).decode())

    def test_missing_context_reproduces_as_no_signal_not_fabricated_trade(self):
        frame, now = _vwap_displacement_frame(); frame.attrs.clear()
        self.assertIsNone(self.capture(DISPLACEMENT, frame, now, ticker='TSLA'))
        self.assertIsNone(self.verify()[0]['signal'])

    def test_clock_boundary_is_not_verified(self):
        self.capture(RECOVERY, self.recovery_frame(), '2026-08-10 09:47:59',
                     end=pd.Timestamp('2026-08-10 09:48:00', tz='America/New_York'))
        with self.assertRaisesRegex(ValueError, 'clock bracket'): self.verify()

    def test_foreign_or_unidentified_scope_does_not_capture(self):
        spec = evidence.SPECS[RECOVERY]; fn = getattr(importlib.import_module(spec[0]), spec[1])
        self.assertIsNone(self.recorder.begin(RECOVERY, self.recovery_frame(), 'META', fn))
        for value in (None, 'paper'):
            self.settings['paper_trading'] = value
            self.assertIsNone(self.recorder.begin(RECOVERY, self.recovery_frame(), 'SPY', fn))
        self.assertFalse(self.path.exists())

    def test_storage_failure_never_changes_signal(self):
        with patch.object(storage, 'append', side_effect=OSError('disk full')):
            self.assertIsNotNone(self.capture(RECOVERY, self.recovery_frame(), '2026-08-10 09:47'))

    def test_budget_shared_and_does_not_prune(self):
        frame = self.recovery_frame()
        self.capture(RECOVERY, frame, '2026-08-10 09:47')
        before = self.path.read_bytes()
        with patch.object(storage, 'MAX_DATABASE_BYTES', self.path.stat().st_size):
            self.capture(RECOVERY, frame, '2026-08-10 09:47')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path)+'-wal').exists())

    def test_readonly_report_scoped_and_missing_blob_rejected(self):
        self.capture(RECOVERY, self.recovery_frame(), '2026-08-10 09:47')
        before = self.path.read_bytes()
        result = report(self.path, account_digest=self.account, paper=True)
        self.assertFalse(result['whole_account_replay_complete'])
        with self.assertRaises(ValueError): report(self.path, account_digest=self.account, paper=False)
        self.assertEqual(self.path.read_bytes(), before)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('DELETE FROM input_blobs'); conn.commit()
        with self.assertRaisesRegex(ValueError, 'Missing'): self.verify()

    def test_tampered_transition_is_rejected(self):
        self.capture(RECOVERY, self.recovery_frame(), '2026-08-10 09:47')
        packed, _ = self.rows()[0]
        row = storage.decode(json.loads(zlib.decompress(packed))); row['signal'] = None
        raw = storage.canonical(row)
        with self.assertRaisesRegex(ValueError, 'does not reproduce'):
            verify_record(zlib.compress(raw), hashlib.sha256(raw).hexdigest(), self.blob)

    def test_actual_evaluator_error_reproduces(self):
        frame = self.recovery_frame(); frame['time'] = 'invalid-time'
        self.capture(RECOVERY, frame, '2026-08-10 09:47')
        self.assertIsNotNone(self.verify()[0]['error'])

    def test_shared_history_chunks_do_not_duplicate_unchanged_prefix(self):
        frame, now = _vwap_displacement_frame()
        prior = tuple((pd.Timestamp('2026-09-02') + pd.Timedelta(minutes=i), 100., 101., 99., 100., 100.)
                      for i in range(256))
        frame.attrs['multi_session_bars'] = prior + frame.attrs['multi_session_bars']
        self.capture(DISPLACEMENT, frame, now, ticker='TSLA')
        with closing(sqlite3.connect(self.path)) as conn:
            before = {r[0] for r in conn.execute('SELECT digest FROM input_blobs')}
        history = frame.attrs['multi_session_bars']
        frame.attrs['multi_session_bars'] = history + ((now, 102., 103., 101., 102., 100.),)
        self.capture(DISPLACEMENT, frame, now, ticker='TSLA')
        with closing(sqlite3.connect(self.path)) as conn:
            after = {r[0] for r in conn.execute('SELECT digest FROM input_blobs')}
        self.assertTrue(before <= after)
        self.assertEqual(len(after - before), 2)  # Only changed tail and its manifest.
        self.verify()

    def route(self, recorder, *, quiet=False, enabled=True):
        import strategy_router.route as router
        spec = evidence.SPECS[RECOVERY]
        fn = getattr(importlib.import_module(spec[0]), spec[1])
        frame = self.recovery_frame()
        now = pd.Timestamp('2026-08-10 09:47', tz='America/New_York')
        with patch.object(router, 'ACTIVE_STRATEGIES', [(RECOVERY, fn)]), \
             patch.object(router, '_authorized_for_order', return_value=True), \
             patch.object(router, 'check_kill_lock', return_value=(False, '')), \
             patch.object(router, '_emit_signal_annotation'), \
             patch.object(router, 'compute_adx', return_value=30.), \
             patch('auth.context.get_current_user_id', return_value='test-user'), \
             patch('config.get_settings', return_value=self.settings), \
             patch.object(pd.Timestamp, 'now', return_value=now):
            return router.route_signals(frame, 'SPY', enabled_strategies={RECOVERY} if enabled else set(),
                prepared_today=frame, preserve_reviewed_paid_rules=True, quiet=quiet, decision_recorder=recorder)

    def test_router_records_real_native_result(self):
        signals = self.route(self.recorder)
        self.assertEqual(len(signals), 1)
        self.assertEqual(self.verify()[0]['signal']['strategy_id'], RECOVERY)

    def test_broken_observer_cannot_suppress_actual_order_signal(self):
        recorder = Mock()
        recorder.begin.side_effect = RuntimeError('storage unavailable')
        recorder.finish.side_effect = RuntimeError('storage unavailable')
        self.assertEqual(len(self.route(recorder)), 1)

    def test_quiet_and_disabled_routes_never_capture(self):
        recorder = Mock()
        self.route(recorder, quiet=True)
        self.route(recorder, enabled=False)
        recorder.begin.assert_not_called()
        recorder.finish.assert_not_called()


if __name__ == '__main__': unittest.main()
