from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.jobs.reprice_paid_markouts_fixed_holds import reprice_day


class RepricePaidMarkoutsTests(unittest.TestCase):
    def test_reuses_contract_and_entry_and_finds_each_first_bid(self) -> None:
        signal = datetime(2026, 5, 13, 13, 40, tzinfo=timezone.utc)
        entry = signal + timedelta(minutes=1, seconds=12)
        contract = "SPY   260522C00600000"
        row = {
            "signal_time": signal.isoformat(), "entry_time": entry.isoformat(),
            "contract": contract, "entry_ask": 2.00, "exit_time": "old", "exit_bid": 1.00,
            "return_pct": -50.0, "underlying_exit": 600.0,
        }
        with TemporaryDirectory() as directory:
            source = Path(directory) / "opra.csv"
            source.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                f"{(signal + timedelta(minutes=6)).isoformat()},{contract},2.20,2.30\n"
                f"{(signal + timedelta(minutes=6, seconds=20)).isoformat()},{contract},2.30,2.40\n"
                f"{(signal + timedelta(minutes=11)).isoformat()},{contract},1.80,1.90\n",
                encoding="utf-8",
            )
            result, missing = reprice_day(source, [row], (5, 10), ticker="SPY")
        self.assertEqual([], missing)
        self.assertEqual(2.20, result[5][0]["exit_bid"])
        self.assertEqual(10.0, result[5][0]["return_pct"])
        self.assertEqual(1.80, result[10][0]["exit_bid"])
        self.assertEqual(contract, result[10][0]["contract"])
        self.assertEqual(entry.isoformat(), result[10][0]["entry_time"])
        self.assertIsNone(result[10][0]["underlying_exit"])

    def test_reports_missing_exit_without_inventing_a_quote(self) -> None:
        signal = datetime(2026, 5, 13, 13, 40, tzinfo=timezone.utc)
        row = {
            "signal_time": signal.isoformat(), "entry_time": (signal + timedelta(minutes=1)).isoformat(),
            "contract": "SPY   260522C00600000", "entry_ask": 2.00,
        }
        with TemporaryDirectory() as directory:
            source = Path(directory) / "empty.csv"
            source.write_text("ts_recv,symbol,bid_px_00,ask_px_00\n", encoding="utf-8")
            result, missing = reprice_day(source, [row], (5,), ticker="SPY")
        self.assertEqual([], result[5])
        self.assertEqual("no_executable_bid_in_one_minute_window", missing[0]["reason"])


if __name__ == "__main__":
    unittest.main()
