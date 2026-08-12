from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

import pandas as pd

import strategies.spy_trend_continuation_v2 as spy_trend
from strategies.market_structure import Side, StructureSignal
from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars


class SpyTrendContinuationV2Tests(unittest.TestCase):
    def test_uses_only_closed_one_minute_bars_for_each_five_minute_candle(self) -> None:
        times = pd.date_range("2026-08-10 09:30", periods=10, freq="min")
        frame = pd.DataFrame({
            "time": times, "open": range(100, 110), "high": range(101, 111),
            "low": range(99, 109), "close": range(100, 110), "volume": [1] * 10,
        })
        # At 09:39 the 09:39 minute is still forming, so only 09:30--09:34
        # can form a completed five-minute candle.
        bars = _complete_five_minute_bars(frame, now=datetime(2026, 8, 10, 9, 39))
        self.assertEqual(1, len(bars))
        self.assertEqual(datetime(2026, 8, 10, 9, 30), bars[0].timestamp)
        self.assertEqual(104.0, bars[0].close)

    def test_emits_each_completed_five_minute_trigger_only_once(self) -> None:
        trigger = datetime(2026, 8, 10, 11, 0)
        candidate = StructureSignal(
            Side.LONG, trigger, 101.0, 100.0, 103.0, {"atr": 1.0},
        )
        frame = pd.DataFrame({
            "time": [datetime(2026, 8, 10, 11, 1)],
            "open": [101.0], "high": [101.2], "low": [100.8], "close": [101.0],
        })
        spy_trend._emitted_trigger_by_session.clear()
        with patch.object(spy_trend, "_complete_five_minute_bars", return_value=tuple(range(20))), patch.object(
            spy_trend, "TrendContinuation",
        ) as strategy:
            strategy.return_value.evaluate.return_value = candidate
            first = spy_trend.evaluate(frame, "SPY")
            second = spy_trend.evaluate(frame, "SPY")

        self.assertIsNotNone(first)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
