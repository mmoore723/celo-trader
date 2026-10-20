from datetime import datetime, timedelta
import unittest
import json
from unittest.mock import patch

import pandas as pd

from research.engine.models import Bar
from research.engine.strategies.gap_fill_rth import GapFillRTH
from trading.gap_fill_history import completed_history, valid_session_context, with_history
from trading.tested_strategy_research import _latest_candidate, evaluate_tested_research
from strategies import research_orders
from tests.test_momentum_exit_measurement import frame


def setup():
    prior = datetime(2026, 10, 15, 14, 45)
    day = datetime(2026, 10, 16, 9, 30)
    bars = [Bar(prior + timedelta(minutes=5*i), 100, 100.4, 99.6, 100) for i in range(15)]
    return bars + [Bar(day, 101, 101.2, 100.8, 101),
                   Bar(day + timedelta(minutes=5), 101, 101.25, 99.75, 100.25)]


class GapFillSessionHistoryTests(unittest.TestCase):
    def test_captured_friday_reclaims_are_not_reclaims_of_actual_close(self):
        for hour, minute, low, high, close in [(13, 10, 342.495, 343.24, 343.03),
                                              (14, 5, 342.365, 342.97, 342.92)]:
            prior = [Bar(datetime(2026, 10, 15, 14, 45) + timedelta(minutes=5*i),
                         342.70, 342.9, 342.5, 342.70) for i in range(14)]
            today = [Bar(datetime(2026, 10, 16, 9, 30), 346.085, 346.5, 345.5, 346),
                     Bar(datetime(2026, 10, 16, hour, minute), close, high, low, close)]
            self.assertIsNone(_latest_candidate(GapFillRTH(), tuple(prior + today), research_strategy_id='V2_GAP_FILL_RTH'))
            actual_close = Bar(datetime(2026, 10, 15, 15, 55), 342.59, 342.7, 341.8, 341.91)
            self.assertIsNone(_latest_candidate(GapFillRTH(), tuple(prior + [actual_close] + today), research_strategy_id='V2_GAP_FILL_RTH'))

    def test_corrected_short_stop_routes_to_exit_in_paper_and_live(self):
        from tests.test_gap_fill_exit_measurement import seed
        from strategy_health import gap_fill_exit
        from strategy_health.exit_protocols import candidate_metadata
        from trading.research_order_exit import evaluate_exit
        entry = datetime(2026, 9, 10, 10, 5)
        bars = [Bar(entry, 100, 110, 60, 100),
                Bar(entry + timedelta(minutes=5), 100, 100, 80, 81),
                Bar(entry + timedelta(minutes=10), 81, 95, 80, 90)]
        meta = dict(candidate_metadata('V2_GAP_FILL_RTH', GapFillRTH()),
                    authored_exit_state=seed(entry), strategy_version='research.2',
                    research_order_route='exact_research_v1', direction='bearish',
                    trigger_bar=entry.isoformat(), underlying_stop=105, underlying_target=10)
        self.assertEqual(gap_fill_exit.LOW_WATER_PROTOCOL, meta['authored_exit_protocol'])
        for paper in (True, False):
            trade = dict(strategy_id='V2_GAP_FILL_RTH', option_type='put', paper=paper,
                         strategy_context_json=json.dumps(meta))
            self.assertEqual((True, 'research_atr_trailing_stop'),
                             evaluate_exit(trade, entry, entry + timedelta(minutes=11), frame(bars)))
            trade['strategy_context_json'] = json.dumps(dict(meta, authored_exit_protocol=gap_fill_exit.PROTOCOL))
            self.assertEqual((False, 'hold'), evaluate_exit(trade, entry, entry + timedelta(minutes=11), frame(bars)))

    def test_missing_prior_close_cannot_create_false_gap_reclaim(self):
        bars = setup()
        bars = [Bar(b.timestamp.replace(hour=10, minute=5*i), b.open, b.high, b.low, b.close)
                for i, b in enumerate(bars[:6])] + bars[-2:]
        self.assertFalse(valid_session_context(bars))
        self.assertIsNone(_latest_candidate(GapFillRTH(), tuple(bars), research_strategy_id='V2_GAP_FILL_RTH'))

    def test_real_close_and_open_required_and_weekend_supported(self):
        bars = setup()
        self.assertTrue(valid_session_context(bars))
        self.assertIsNotNone(_latest_candidate(GapFillRTH(), tuple(bars), research_strategy_id='V2_GAP_FILL_RTH'))
        self.assertFalse(valid_session_context(bars[:-2] + bars[-1:]))
        self.assertFalse(valid_session_context(bars[:-3] + bars[-2:]))
        monday = [Bar(b.timestamp + timedelta(days=1 if i < 15 else 3), b.open, b.high, b.low, b.close)
                  for i, b in enumerate(bars)]
        self.assertTrue(valid_session_context(monday))
        self.assertFalse(valid_session_context(bars[:-2] + monday[-2:]))

    def test_native_history_fills_prior_close_without_inventing_minutes(self):
        bars = setup()
        native = pd.DataFrame([dict(time=b.timestamp, open=b.open, high=b.high, low=b.low,
                                    close=b.close, volume=b.volume) for b in bars])
        now = datetime(2026, 10, 16, 9, 40)
        merged = with_history(tuple(bars[-2:]), native, now)
        self.assertEqual(tuple(bars), merged)
        self.assertTrue(valid_session_context(merged))
        self.assertEqual(17, len(merged))
        self.assertEqual((), with_history((), native, now))
        self.assertEqual(16, len(completed_history(native, now - timedelta(seconds=1))))
        duplicate = pd.concat([native, native.iloc[-1:]])
        self.assertEqual(16, len(completed_history(duplicate, now)))

    def test_research_and_order_use_identical_repaired_history(self):
        bars = setup(); now = datetime(2026, 10, 16, 9, 40)
        native = pd.DataFrame([dict(time=b.timestamp, open=b.open, high=b.high, low=b.low,
                                    close=b.close, volume=b.volume) for b in bars[:-2]])
        tape = frame(bars[-2:])
        sid = 'V2_GAP_FILL_RTH'
        def load(*args, **kwargs):
            return native if kwargs['timeframe'] == '5Min' else pd.DataFrame()
        with patch.object(research_orders, '_emitted', {}), patch('trading.tested_strategy_research._emitted', set()), \
                patch('database.load_scanner_candles', side_effect=load):
            expected = evaluate_tested_research(tape, 'AAPL', [sid], scope='gap-history', now=now, history_5m=native)
            actual = research_orders.evaluate(tape, 'AAPL', execution_scope='gap-history', now=now, strategy_id=sid)
        self.assertEqual(1, len(expected))
        self.assertIsNotNone(actual)
        for key in ('gap_pct', 'underlying_stop', 'underlying_target', 'authored_exit_state', 'authored_exit_protocol'):
            self.assertEqual(expected[0].meta[key], actual.meta[key])


if __name__ == '__main__':
    unittest.main()
