from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

import pandas as pd

import strategies.spy_failed_range_recovery_v2 as recovery


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    times = pd.date_range("2026-08-10 09:30", periods=len(rows), freq="min")
    return pd.DataFrame({
        "time": times, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
        "low": [r[2] for r in rows], "close": [r[3] for r in rows],
        "volume": [100.0] * len(rows), "rvol": [1.5] * len(rows),
    })


class SpyFailedRangeRecoveryV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        recovery._emitted_trigger_by_session.clear()

    def test_excludes_the_current_forming_minute(self) -> None:
        frame = _frame([(100, 101, 99, 100)] * 16)
        bars = recovery._completed_one_minute_bars(frame, now=datetime(2026, 8, 10, 9, 45))
        self.assertEqual(15, len(bars))
        self.assertEqual(datetime(2026, 8, 10, 9, 44), bars[-1].timestamp)

    def test_bearish_recovery_emits_once_after_failed_up_break(self) -> None:
        opening = [(100.0, 101.0, 99.0, 100.0)] * 15
        # Range width=2. A 101.20 close proves the upward break; the next red
        # candle closes back inside with VWAP below it, producing a PUT idea.
        frame = _frame(opening + [(101.0, 101.4, 100.9, 101.2), (101.3, 101.3, 100.8, 100.9)])
        with patch.object(recovery.pd.Timestamp, "now", return_value=pd.Timestamp("2026-08-10 09:47")):
            first = recovery.evaluate(frame, "SPY", execution_scope="user-a")
            second = recovery.evaluate(frame, "SPY", execution_scope="user-a")
        self.assertIsNotNone(first)
        self.assertEqual("bearish", first.direction)
        self.assertEqual("completed_1m_failure_then_next_1m_entry", first.meta["entry_timing"])
        self.assertIn("pa_body_to_range", first.meta)
        self.assertIn("pa_close_to_vwap_atr", first.meta)
        self.assertIsNone(second)

    def test_does_not_catch_up_an_expired_morning_signal(self) -> None:
        opening = [(100.0, 101.0, 99.0, 100.0)] * 15
        signal = [(101.0, 101.4, 100.9, 101.2), (101.3, 101.3, 100.8, 100.9)]
        later = [(100.9, 101.0, 100.7, 100.8)] * 5
        frame = _frame(opening + signal + later)
        with patch.object(recovery.pd.Timestamp, "now", return_value=pd.Timestamp("2026-08-10 09:52")):
            self.assertIsNone(recovery.evaluate(frame, "SPY", execution_scope="restarted-user"))

    def test_never_runs_on_unvalidated_ticker(self) -> None:
        self.assertIsNone(recovery.evaluate(_frame([(100, 101, 99, 100)] * 20), "TSLA"))


if __name__ == "__main__":
    unittest.main()
