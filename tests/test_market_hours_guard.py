from datetime import datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from deploy.market_hours_guard import main, market_hours


class MarketHoursGuardTests(TestCase):
    def test_boundaries_and_weekend(self):
        eastern = ZoneInfo("America/New_York")
        for timestamp, blocked in (
            ("2026-11-05T09:29:59", False),
            ("2026-11-05T09:30:00", True),
            ("2026-11-05T15:59:59", True),
            ("2026-11-05T16:00:00", False),
            ("2026-11-07T12:00:00", False),
        ):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(market_hours(datetime.fromisoformat(timestamp).replace(tzinfo=eastern)), blocked)

    def test_utc_daylight_and_standard_time(self):
        for timestamp in ("2026-07-06T13:30:00+00:00", "2026-11-05T14:30:00+00:00"):
            self.assertTrue(market_hours(datetime.fromisoformat(timestamp)))
        self.assertFalse(market_hours(datetime.fromisoformat("2026-11-05T13:30:00+00:00")))

    def test_rejects_ambiguous_clock(self):
        with self.assertRaises(ValueError):
            market_hours(datetime(2026, 11, 5, 10))

    def test_cli_requires_explicit_override(self):
        with patch("deploy.market_hours_guard.market_hours", return_value=True), patch("builtins.print"):
            with patch("sys.argv", ["guard"]):
                self.assertEqual(main(), 1)
            with patch("sys.argv", ["guard", "--force-market-hours"]):
                self.assertEqual(main(), 0)
