import unittest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch

from scanner.premarket_volume import ET, matched_premarket_rvol, window_volume
from scanner.premarket import daily_premarket_scan
from broker.alpaca_bars import AlpacaBarsMixin


class Feed:
    base = "broker"
    data = "data"

    def __init__(self, current=100, missing=False, repeated=False):
        self.current = current
        self.missing = missing
        self.repeated = repeated
        self.calls = []

    def _get(self, url, params):
        self.calls.append((url, dict(params)))
        if url.endswith("calendar"):
            dates = [date(2026, 10, 15) - timedelta(days=i) for i in range(1, 40)]
            return [{"date": day.isoformat()} for day in dates if day.weekday() < 5]
        day = params["start"][:10]
        volume = self.current if day == "2026-10-15" else 100
        bars = [{"t": day + "T08:00:00-04:00", "v": volume}]
        if self.missing and day == "2026-10-14":
            bars = []
        return {"bars": {"SPY": bars}, "next_page_token": "repeat" if self.repeated else None}


class PremarketVolumeTests(unittest.TestCase):
    def test_missing_prior_close_is_not_a_fabricated_gap_baseline(self):
        client = AlpacaBarsMixin()
        client.data = "data"
        client._get = lambda *args, **kwargs: {"XYZ": {"latestTrade": {"p": 120}, "dailyBar": {"o": 100}}}
        self.assertEqual(client.get_snapshots(["XYZ"])["XYZ"]["previous_daily_close"], 0)

    def test_scanner_clock_uses_dst_aware_new_york(self):
        from scanner.helpers import _et_now
        with patch("scanner.helpers.datetime") as clock:
            clock.now.return_value = datetime(2026, 12, 15, 8, 30, tzinfo=ET)
            self.assertEqual(_et_now(), datetime(2026, 12, 15, 8, 30))
            self.assertEqual(clock.now.call_args.args[0], ET)

    def test_same_window_and_twenty_prior_sessions(self):
        feed = Feed(current=150)
        result = matched_premarket_rvol(feed, ["SPY"], datetime(2026, 10, 15, 8, 30))["SPY"]
        self.assertEqual(result["rvol"], 1.5)
        self.assertEqual(result["premarket_history_sessions"], 20)
        self.assertEqual(len(feed.calls), 22)
        for _, params in feed.calls[1:]:
            self.assertTrue(params["start"].endswith("04:00:00-04:00"))
            self.assertTrue(params["end"].endswith("08:30:00-04:00"))
            self.assertEqual(params["feed"], "iex")

    def test_missing_history_is_not_zero_or_daily_fallback(self):
        self.assertEqual(matched_premarket_rvol(Feed(missing=True), ["SPY"], datetime(2026, 10, 15, 8, 30)), {})

    def test_repeated_pagination_is_rejected(self):
        with self.assertRaises(ValueError):
            matched_premarket_rvol(Feed(repeated=True), ["SPY"], datetime(2026, 10, 15, 8, 30))

    def test_closed_minutes_only_and_duplicates(self):
        bars = [{"t": f"2026-10-15T{clock}-04:00", "v": volume} for clock, volume in
                [("03:59:00", 900), ("04:00:00", 10), ("08:29:00", 20), ("08:29:00", 20), ("08:30:00", 900)]]
        self.assertEqual(window_volume(bars, date(2026, 10, 15), time(8, 30)), 30)

    def test_winter_utc_conversion(self):
        self.assertEqual(window_volume([{"t": "2026-12-15T09:00:00Z", "v": 10}], date(2026, 12, 15), time(8, 30)), 10)
        self.assertIsNone(window_volume([{"t": "2026-12-15T08:59:00Z", "v": 10}], date(2026, 12, 15), time(8, 30)))

    def test_no_scan_window_before_four(self):
        feed = Feed()
        self.assertEqual(matched_premarket_rvol(feed, ["SPY"], datetime(2026, 10, 15, 3, 59)), {})
        self.assertEqual(feed.calls, [])

    def test_scanner_threshold_force_and_no_gap_cap(self):
        class ScannerFeed:
            def get_optionable_assets(self):
                return ["XYZ"]

            def get_snapshots(self, symbols):
                return {"XYZ": {"price": 120, "prev_close": 100, "open_price": 90, "daily_vol": 9000000}}

        for rvol, expected in [(0.99, False), (1.0, True), (1.1, True), (None, False)]:
            with self.subTest(rvol=rvol), \
                 patch("config.get_settings", return_value={}), \
                 patch("scanner.premarket._et_now", return_value=datetime(2026, 10, 15, 8, 30)), \
                 patch("scanner.premarket.get_consolidated_daily_bars", return_value={"XYZ": [{"h": 103, "l": 98, "c": 100, "v": 3000000}] * 20}), \
                 patch("scanner.premarket.matched_premarket_rvol", return_value={} if rvol is None else {"XYZ": {"rvol": rvol}}), \
                 patch("scanner.premarket._write_daily_universe") as write, \
                 patch("scanner.premarket._write_state"):
                daily_premarket_scan(ScannerFeed(), force=True)
                selected = write.call_args.args[2]
                self.assertEqual(bool(selected), expected)
                self.assertEqual(write.call_args.args[3]["phase"], "premarket")
                if expected:
                    self.assertEqual(selected[0]["gap_pct"], 20.0)


if __name__ == "__main__":
    unittest.main()
