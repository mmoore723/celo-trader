from datetime import datetime, timedelta
import unittest

from research.engine.models import Bar, Side, Signal
from research.jobs.diagnose_paid_range_sweep_transfer import _enriched, outcome_alignment


class RangeSweepTransferDiagnosticTests(unittest.TestCase):
    def test_separates_chart_direction_from_option_capture(self) -> None:
        rows = [
            {"underlying_return_pct": 1.0, "return_pct": 5.0},
            {"underlying_return_pct": 1.0, "return_pct": -2.0},
            {"underlying_return_pct": -1.0, "return_pct": 1.0},
            {"underlying_return_pct": -1.0, "return_pct": -3.0},
        ]
        result = outcome_alignment(rows)
        self.assertEqual(50.0, result["underlying_direction_hit_rate_pct"])
        self.assertEqual(50.0, result["option_capture_rate_when_underlying_up_pct"])
        self.assertTrue(all(group["count"] == 1 for group in result["quadrants"].values()))

    def test_ignores_rows_without_an_underlying_exit(self) -> None:
        result = outcome_alignment([{"underlying_return_pct": None, "return_pct": 1.0}])
        self.assertEqual(0, result["measured_trades"])
        self.assertIsNone(result["underlying_direction_hit_rate_pct"])

    def test_enrichment_uses_only_an_underlying_bar_complete_at_exit(self) -> None:
        start = datetime.fromisoformat("2026-01-02T10:00:00-05:00")
        bars = tuple(
            Bar(start + timedelta(minutes=index), 100, 102, 99, close, 100)
            for index, close in enumerate((100, 101, 99))
        )
        signal = Signal(
            "RANGE_SWEEP", Side.LONG, bars[1].timestamp,
            101, 99, 105,
            {
                "atr": 1.0,
                "range_low": 100.0,
                "efficiency_ratio": 0.2,
            },
        )
        markout = {
            "signal_time": bars[1].timestamp.isoformat(),
            "exit_time": (bars[2].timestamp + timedelta(seconds=30)).isoformat(),
            "underlying_entry": 100.0,
            "underlying_exit": 99.0,
            "entry_ask": 2.0,
            "return_pct": 1.0,
        }
        enriched = _enriched(markout, signal, bars)
        # The 10:02 bar is still open at 10:02:30, so the completed 10:01
        # close (101), not its future 10:03 close (99), determines direction.
        self.assertEqual(1.0, enriched["underlying_return_pct"])


if __name__ == "__main__":
    unittest.main()
