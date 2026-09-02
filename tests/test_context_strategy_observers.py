from __future__ import annotations

from datetime import time
import unittest

import pandas as pd

from strategy_router.indicator_frame import _build_indicator_frame
from strategies import context_strategy_observers as observers


def _row(timestamp: pd.Timestamp, *, close: float = 100.0, high: float = 100.2,
         low: float = 99.8, volume: float = 100.0) -> dict:
    return {
        "time": timestamp, "open": 100.0, "high": high,
        "low": low, "close": close, "volume": volume,
    }


def _nr7_frame() -> tuple[pd.DataFrame, pd.Timestamp]:
    rows: list[dict] = []
    sessions = pd.bdate_range("2026-07-30", periods=8)
    for session_index, session in enumerate(sessions[:-1]):
        narrow = session_index == len(sessions[:-1]) - 1
        for offset in range(0, 390, 5):
            timestamp = session + pd.Timedelta(hours=9, minutes=30 + offset)
            rows.append(_row(
                timestamp,
                high=100.5 if narrow else 102.0,
                low=99.5 if narrow else 98.0,
            ))
    current = sessions[-1]
    for offset in range(21):
        timestamp = current + pd.Timedelta(hours=9, minutes=30 + offset)
        if offset == 20:
            rows.append(_row(timestamp, close=101.0, high=101.2, low=99.9, volume=200.0))
        else:
            rows.append(_row(timestamp))
    full = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    return _build_indicator_frame(full), current + pd.Timedelta(hours=10)


class ContextStrategyObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        observers._emitted.clear()

    def test_indicator_frame_carries_read_only_multi_session_context(self) -> None:
        today, _now = _nr7_frame()
        tape = today.attrs.get("multi_session_bars")
        self.assertIsInstance(tape, tuple)
        self.assertGreater(len(tape), len(today))

    def test_nr7_orb_emits_exact_volume_confirmed_breakout(self) -> None:
        today, now = _nr7_frame()
        signal = observers.evaluate_orb_nr7_inside(today, ticker="TSLA", now=now)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(observers.ORB_NR7_INSIDE, signal.strategy_id)
        self.assertEqual("bullish", signal.direction)
        self.assertEqual(time(9, 51), signal.trigger_bar.time())
        self.assertTrue(signal.meta["nr7"])
        self.assertEqual(2.0, signal.meta["volume_ratio_20"])
        self.assertTrue(signal.meta["observation_only"])

    def test_nr7_orb_deduplicates_same_signal(self) -> None:
        today, now = _nr7_frame()
        self.assertIsNotNone(observers.evaluate_orb_nr7_inside(today, ticker="TSLA", now=now))
        self.assertIsNone(observers.evaluate_orb_nr7_inside(today, ticker="TSLA", now=now))

    def test_observer_fails_closed_without_prior_context(self) -> None:
        today, now = _nr7_frame()
        today.attrs.clear()
        self.assertIsNone(observers.evaluate_orb_nr7_inside(today, ticker="TSLA", now=now))

    def test_observer_rejects_out_of_scope_ticker(self) -> None:
        today, now = _nr7_frame()
        self.assertIsNone(observers.evaluate_squeeze_macd(today, ticker="SPY", now=now))


if __name__ == "__main__":
    unittest.main()
