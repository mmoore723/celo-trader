import unittest
from datetime import datetime, date, time, timedelta
from unittest.mock import patch

from scanner.premarket_volume import ET, matched_premarket_rvol, window_volume
from scanner.premarket import daily_premarket_scan
from broker.alpaca_bars import AlpacaBarsMixin


class Feed:
    base = "broker"
    data = "data"

    def __init__(self, current=100, missing=False):
        self.current = current
        self.missing = missing
        self.calls = []

    def _get(self, url, params):
        self.calls.append((url, dict(params)))
        if url.endswith("calendar"):
            dates = [date(2026, 10, 15) - timedelta(days=i) for i in range(1, 40)]
            return [{"date": day.isoformat()} for day in dates if day.weekday() < 5]
        raise AssertionError("Alpaca volume must not be requested")


class ConsolidatedFeed:
    base = "https://api.tradier.com/v1"

    def __init__(self, current=150, missing=False):
        self.calls = []
        self.current = current
        self.missing = missing

    def _get(self, url, params):
        self.calls.append((url, params))
        dates = [date(2026, 10, 15) - timedelta(days=i) for i in range(10)]
        rows = [{"time": f"{day}T08:00:00", "volume": self.current if day.day == 15 else 100}
                for day in dates if day.weekday() < 5 and not (self.missing and day.day == 14)]
        return {"series": {"data": rows}}


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

    def test_same_window_consolidated_ten_calendar_days(self):
        feed, tradier = Feed(), ConsolidatedFeed()
        result = matched_premarket_rvol(feed, ["SPY"], datetime(2026, 10, 15, 8, 30), tradier=tradier)["SPY"]
        self.assertEqual(result["rvol"], 1.5)
        self.assertEqual(result["premarket_history_sessions"], 7)
        self.assertEqual(result["premarket_history_days"], 10)
        self.assertEqual(result["premarket_volume_feed"], "tradier_consolidated")
        self.assertEqual(len(feed.calls), 1)
        params = tradier.calls[0][1]
        self.assertEqual(params["start"], "2026-10-06 04:00")
        self.assertEqual(params["end"], "2026-10-15 08:30")
        self.assertEqual(params["session_filter"], "all")

    def test_missing_history_is_not_zero_or_daily_fallback(self):
        self.assertEqual(matched_premarket_rvol(Feed(), ["SPY"], datetime(2026, 10, 15, 8, 30), tradier=ConsolidatedFeed(missing=True)), {})

    def test_sandbox_is_rejected(self):
        tradier = ConsolidatedFeed()
        tradier.base = "https://sandbox.tradier.com/v1"
        with self.assertRaises(ValueError):
            matched_premarket_rvol(Feed(), ["SPY"], datetime(2026, 10, 15, 8, 30), tradier=tradier)

    def test_feed_failure_never_falls_back_to_iex(self):
        tradier = ConsolidatedFeed()
        with patch.object(tradier, "_get", side_effect=RuntimeError("offline")):
            self.assertEqual(matched_premarket_rvol(Feed(), ["SPY"], datetime(2026, 10, 15, 8, 30), tradier=tradier), {})

    def test_one_symbol_failure_does_not_discard_other_results(self):
        tradier = ConsolidatedFeed()
        response = tradier._get("/markets/timesales", {})
        with patch.object(tradier, "_get", side_effect=[RuntimeError("offline"), response]), \
             patch("scanner.premarket_volume.clock.sleep"):
            results = matched_premarket_rvol(Feed(), ["BAD", "SPY"], datetime(2026, 10, 15, 8, 30), tradier=tradier)
        self.assertEqual(set(results), {"SPY"})

    def test_production_token_is_selected_without_switching_trading_mode(self):
        from scanner.premarket_volume import _market_client
        with patch("config.get_api_keys", return_value={"tradier_market_api_key": "production", "tradier_api_key": "sandbox"}), \
             patch("broker.tradier_client.TradierClient") as constructor:
            _market_client()
        constructor.assert_called_once_with(api_key="production", base_url="https://api.tradier.com/v1")

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
