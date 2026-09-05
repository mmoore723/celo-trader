from __future__ import annotations

from datetime import date, datetime, timedelta
import unittest

from research.jobs.audit_spy_failed_range_generalization import (
    SessionCandidate,
    confirmation_entry_index,
    outcome,
    summarize,
)
from strategies.market_structure import Bar, Side


def _bars() -> tuple[Bar, ...]:
    start = datetime(2026, 1, 2, 9, 30)
    closes = [100.0, 100.2, 100.4, 100.6, 100.8, 101.0, 101.2, 101.4]
    closes.extend(101.4 + 0.1 * index for index in range(50))
    return tuple(
        Bar(start + timedelta(minutes=index), close - 0.02, close + 0.05,
            close - 0.05, close, 1_000)
        for index, close in enumerate(closes)
    )


def _candidate(side: Side = Side.LONG) -> SessionCandidate:
    bars = _bars()
    return SessionCandidate(
        day=date(2026, 1, 2), side=side, bars=bars,
        breakout_index=4, trigger_index=5,
        range_high=101.0, range_low=100.0, vwap=100.5,
    )


class SpyFailedRangeGeneralizationTests(unittest.TestCase):
    def test_baseline_enters_next_minute_and_exits_after_full_hold(self) -> None:
        candidate = _candidate()
        row = outcome(
            candidate, confirmation_entry_index(candidate, "baseline"),
            hold_minutes=30, round_trip_cost_pct=0.02,
        )
        self.assertIsNotNone(row)
        self.assertEqual(candidate.bars[6].timestamp.isoformat(), row["entry_time"])
        self.assertEqual(candidate.bars[36].timestamp.isoformat(), row["exit_time"])

    def test_confirmation_cannot_use_confirmation_bar_open_as_fill(self) -> None:
        candidate = _candidate()
        entry_index = confirmation_entry_index(candidate, "next_bar_follow_through")
        self.assertEqual(7, entry_index)

    def test_summary_calculates_profit_factor_from_net_returns(self) -> None:
        result = summarize([
            {"net_return_pct": 3.0}, {"net_return_pct": -1.0},
            {"net_return_pct": 1.0}, {"net_return_pct": -1.0},
        ])
        self.assertEqual(4, result["trades"])
        self.assertEqual(2, result["wins"])
        self.assertEqual(2.0, result["profit_factor"])
        self.assertEqual(2.0, result["net_return_pct"])


if __name__ == "__main__":
    unittest.main()
