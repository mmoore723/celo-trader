from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from strategy_health.structural_capture import ROUTER_LEVEL_RULES, router_entry_levels


class RouterLevelTests(unittest.TestCase):
    def fixture(self, strategy, side='bullish'):
        rule = ROUTER_LEVEL_RULES[strategy]
        at = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
        meta = {'entry_timing': rule[3], 'v2_stop': 1}
        field = rule[0] if side == 'bullish' else rule[1]
        if field:
            meta[field] = 100
        meta['breakout_time'] = at.isoformat()
        signal = SimpleNamespace(strategy_id=strategy, direction=side, meta=meta, trigger_bar=at)
        return signal, at+timedelta(minutes=5)

    def test_every_registered_route_and_side_preserves_exact_raw_value(self):
        for strategy, rule in ROUTER_LEVEL_RULES.items():
            for side in ('bullish', 'bearish'):
                with self.subTest(strategy=strategy, side=side):
                    signal, now = self.fixture(strategy, side)
                    before = dict(signal.meta)
                    out = router_entry_levels(signal, now)['structural_levels']
                    field = rule[0] if side == 'bullish' else rule[1]
                    if field is None:
                        self.assertEqual('missing', out['status'])
                    else:
                        self.assertEqual('captured', out['status'])
                        self.assertEqual(100, out['support' if side == 'bullish' else 'resistance'])
                        self.assertEqual(field, out['source_field'])
                        self.assertEqual(signal.trigger_bar+timedelta(minutes=rule[5]),
                                         datetime.fromisoformat(out['source_completed_at']))
                    self.assertEqual(before, signal.meta)

    def test_future_candle_unknown_convention_missing_level_never_fallback(self):
        for change in ('future', 'timing', 'missing', 'boolean'):
            signal, now = self.fixture('V2_SPY_TREND_CONT')
            if change == 'future': signal.trigger_bar = now
            if change == 'timing': signal.meta['entry_timing'] = 'unknown'
            if change == 'missing': signal.meta.pop('pa_nearest_support')
            if change == 'boolean': signal.meta['pa_nearest_support'] = True
            self.assertEqual('missing',router_entry_levels(signal,now)['structural_levels']['status'])

    def test_existing_capture_not_overwritten_and_other_strategies_untouched(self):
        signal, now = self.fixture('V2_SPY_TREND_CONT')
        signal.meta['structural_levels'] = {'status':'missing'}
        self.assertEqual({},router_entry_levels(signal,now))
        signal.strategy_id='OTHER'
        self.assertEqual({},router_entry_levels(signal,now))

    def test_naive_source_is_explicit_eastern_not_utc(self):
        signal, now = self.fixture('V2_SPY_TREND_CONT')
        signal.trigger_bar=datetime(2026,11,10,10)
        out=router_entry_levels(signal,now)['structural_levels']
        self.assertEqual('2026-11-10T10:05:00-05:00',out['source_completed_at'])

    def test_retouch_uses_breakout_not_forming_retouch_minute(self):
        signal, now = self.fixture('V2_ORB_PULLBACK')
        signal.trigger_bar=now
        out=router_entry_levels(signal,now)['structural_levels']
        self.assertEqual('2026-11-10T15:01:00+00:00',out['source_completed_at'])

    def test_original_router_record_contains_same_frozen_evidence_as_signal(self):
        import json
        import sqlite3
        from contextlib import contextmanager
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from database.schema import _CREATE_SHADOW_CANDIDATES
        from shadow_ledger import record_router_candidate
        signal, now = self.fixture('V2_SPY_TREND_CONT')
        signal.confidence=.8
        with TemporaryDirectory() as directory:
            path=Path(directory)/'test.db'
            @contextmanager
            def connect():
                db=sqlite3.connect(path)
                try:
                    with db: yield db
                finally: db.close()
            with connect() as db: db.executescript(_CREATE_SHADOW_CANDIDATES)
            with patch('shadow_ledger.get_conn',connect), patch('shadow_ledger._now_et',return_value=now), \
                 patch('config.get_settings',return_value={'active_broker_account_id':'fixture'}):
                record_router_candidate('SPY',signal,101)
                record_router_candidate('SPY',signal,101)
            with connect() as db:
                rows=db.execute('SELECT observed_at,metadata_json FROM shadow_candidates').fetchall()
            self.assertEqual(1,len(rows))
            saved=json.loads(rows[0][1])
            self.assertEqual(signal.meta['structural_levels'],saved['structural_levels'])
            self.assertEqual(now.isoformat(),saved['structural_levels']['recorded_at'])
            self.assertEqual(100,saved['pa_nearest_support'])
            self.assertEqual(1,saved['v2_stop'])
