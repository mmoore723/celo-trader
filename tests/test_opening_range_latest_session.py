"""Regression coverage for multi-session opening-range inputs."""

import unittest

import pandas as pd

from signals.ranges import get_opening_range


class OpeningRangeLatestSessionTests(unittest.TestCase):
    def test_uses_only_latest_session_when_broker_tail_contains_yesterday(self) -> None:
        rows = [
            {"time": "2026-08-19 09:30:00", "open": 776.0, "high": 776.69, "low": 775.80, "close": 776.2, "volume": 100},
            {"time": "2026-08-19 09:35:00", "open": 776.2, "high": 776.50, "low": 775.36, "close": 775.8, "volume": 110},
            {"time": "2026-08-19 09:40:00", "open": 775.8, "high": 776.10, "low": 775.50, "close": 775.9, "volume": 120},
            {"time": "2026-08-20 09:30:00", "open": 766.0, "high": 766.40, "low": 765.30, "close": 765.8, "volume": 200},
            {"time": "2026-08-20 09:35:00", "open": 765.8, "high": 766.10, "low": 764.90, "close": 765.2, "volume": 210},
            {"time": "2026-08-20 09:40:00", "open": 765.2, "high": 765.70, "low": 763.80, "close": 764.1, "volume": 220},
        ]

        result = get_opening_range(pd.DataFrame(rows))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["bars"], 3)
        self.assertEqual(result["high"], 766.40)
        self.assertEqual(result["low"], 763.80)
        self.assertEqual(result["open"], 766.0)
        self.assertEqual(result["close"], 764.1)
        self.assertEqual(result["volume"], 630.0)
        self.assertEqual(str(result["time"]), "2026-08-20 09:30:00")


if __name__ == "__main__":
    unittest.main()
