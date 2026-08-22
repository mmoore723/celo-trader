from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from research.engine.models import Bar
from research.jobs.test_suggested_strategy_changes import (
    _ema200_aligned,
    _failed_range_plan,
    _metric,
)


def _bar(timestamp: datetime, close: float, *, high: float | None = None,
         low: float | None = None) -> Bar:
    return Bar(
        timestamp=timestamp,
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=1_000,
    )


class SuggestedStrategyChangesTest(unittest.TestCase):
    def test_metric_uses_option_returns_and_profit_factor(self) -> None:
        result = _metric((
            {"return_pct": 10.0},
            {"return_pct": -5.0},
            {"return_pct": 2.0},
        ))
        self.assertEqual(result["trades"], 3)
        self.assertEqual(result["win_rate_pct"], 66.67)
        self.assertEqual(result["median_return_pct"], 2.0)
        self.assertEqual(result["profit_factor"], 2.4)

    def test_failed_range_stop_is_initial_2_5_atr_and_causal(self) -> None:
        start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
        bars = tuple(_bar(start + timedelta(minutes=index), 100.0) for index in range(20))
        signal_time = start + timedelta(minutes=20)
        entry_time = signal_time + timedelta(minutes=1)
        # The adverse bar starts after entry and crosses the initial ATR stop.
        bars += (_bar(entry_time, 100.0, high=100.5, low=96.0),)
        target, context = _failed_range_plan({
            "signal_time": signal_time.isoformat(),
            "entry_time": entry_time.isoformat(),
            "underlying_entry": 100.0,
            "side": "long",
        }, bars)
        self.assertEqual(context["exit_reason"], "initial_2_5atr_stop")
        self.assertEqual(target, entry_time + timedelta(minutes=1))

    def test_ema200_filter_uses_only_completed_bars(self) -> None:
        start = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
        bars = tuple(_bar(start + timedelta(minutes=15 * index), 100.0 + index * 0.1)
                     for index in range(200))
        signal_time = start + timedelta(minutes=15 * 200)
        aligned, context = _ema200_aligned({
            "signal_time": signal_time.isoformat(),
            "side": "long",
        }, bars)
        self.assertTrue(aligned)
        self.assertEqual(context["bars"], 200)

        # A future crash cannot change the already-issued signal decision.
        future = _bar(signal_time, 1.0, high=1.5, low=0.5)
        aligned_after, context_after = _ema200_aligned({
            "signal_time": signal_time.isoformat(),
            "side": "long",
        }, bars + (future,))
        self.assertEqual((aligned_after, context_after), (aligned, context))


if __name__ == "__main__":
    unittest.main()
