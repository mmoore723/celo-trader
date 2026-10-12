import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from api.routes.market import _rank_premarket_results, build_premarket_report
from trading.state import _now_et


def yf_frame(symbol: str, rows: list[tuple], index: pd.DatetimeIndex) -> pd.DataFrame:
    columns = pd.MultiIndex.from_tuples(
        [(symbol, name) for name in ("Open", "High", "Low", "Close", "Volume")]
    )
    return pd.DataFrame(rows, index=index, columns=columns)


class _Alpaca:
    def get_snapshots(self, tickers):
        return {
            ticker: {"price": 123.0, "prev_close": 120.0, "daily_vol": 200_000}
            for ticker in tickers
        }


class PremarketReportTests(unittest.TestCase):
    def test_reports_rank_from_highest_fit_score_to_lowest(self):
        rows = [
            {"ticker": "SPY", "fit_score": 64, "tradeable_today": True, "is_pinned": True},
            {"ticker": "AMZN", "fit_score": 91, "tradeable_today": False, "is_pinned": False},
            {"ticker": "QQQ", "fit_score": 78, "tradeable_today": True, "is_pinned": False},
        ]
        ranked = _rank_premarket_results(rows)
        self.assertEqual(["AMZN", "QQQ", "SPY"], [row["ticker"] for row in ranked])
        self.assertEqual([1, 2, 3], [row["rank"] for row in ranked])

    def test_report_uses_real_multiframe_data_and_last_completed_daily_bar(self):
        now = _now_et()
        daily_index = pd.DatetimeIndex([
            pd.Timestamp(now.date() - timedelta(days=days))
            for days in range(23, -1, -1)
        ])
        daily_rows = [
            (close - 1, close + 1, close - 1, close, 1_000_000)
            for close in range(98, 122)
        ]
        daily_rows[-2] = (119, 121, 118, 120, 1_000_000)
        daily_rows[-1] = (998, 1_000, 997, 999, 1_000_000)  # partial today; never "yesterday"

        minute_index = pd.date_range(now - timedelta(minutes=15), periods=16, freq="min")
        minute_rows = [(100+i, 101+i, 99+i, 100+i, 10_000) for i in range(16)]
        hour_index = pd.date_range(now - timedelta(hours=10), periods=11, freq="h")
        hour_rows = [(100+i, 101+i, 99+i, 100+i, 100_000) for i in range(11)]

        def download(_tickers, **kwargs):
            interval = kwargs["interval"]
            if interval == "1d":
                return yf_frame("SPY", daily_rows, daily_index)
            if interval == "1m":
                return yf_frame("SPY", minute_rows, minute_index)
            if interval == "60m":
                return yf_frame("SPY", hour_rows, hour_index)
            raise AssertionError(interval)

        fake_yfinance = SimpleNamespace(download=download)
        with patch("api.routes.market.universe_path", Path("/missing/premarket-universe.json")), \
             patch("config.get_settings", return_value={"watchlist": ["SPY"], "paper_trading": True}), \
             patch.dict("sys.modules", {"yfinance": fake_yfinance}), \
             patch("broker.get_clients", return_value=(_Alpaca(), object())):
            report = build_premarket_report("")

        self.assertEqual(1, len(report))
        row = report[0]
        self.assertEqual(120.0, row["prev_close"])
        self.assertEqual(["Minute", "Hour", "Day", "Week", "Month"], [item["label"] for item in row["timeframes"]])
        self.assertIsNotNone(row["best_strategy"])
        self.assertEqual(row["fit_score"], row["readiness_score"])
        self.assertNotIn("Wait for ORB (9:30", row["entry_note"])


if __name__ == "__main__":
    unittest.main()
