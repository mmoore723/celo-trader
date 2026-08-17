from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from research.engine.models import Bar, Side, Signal
from research.jobs.diagnose_paid_option_eligibility import compression_config, diagnose_file


class PaidOptionEligibilityDiagnosticTests(unittest.TestCase):
    def test_uses_the_same_named_variant_as_the_paid_tuning_job(self) -> None:
        config = compression_config("wider_baseline")
        self.assertEqual("12:30:00", config.compression_start.isoformat())
        self.assertEqual("13:15:00", config.compression_end.isoformat())
        self.assertEqual("15:00:00", config.entry_end.isoformat())
        self.assertEqual(.004, config.max_compression_pct)

        with self.assertRaisesRegex(ValueError, "unknown compression variant"):
            compression_config("unknown")

    def test_counts_rejection_reasons_and_complete_pair(self) -> None:
        bars = (
            Bar(datetime.fromisoformat("2026-06-01T13:19:00-04:00"), 100, 101, 99, 100, 1000),
            Bar(datetime.fromisoformat("2026-06-01T13:20:00-04:00"), 100, 101, 99, 100, 1000),
        )
        signal = Signal("TEST", Side.LONG, bars[0].timestamp, 100, 99, 102, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            path.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                "2026-06-01T13:20:00-04:00,SPY   260612C00101000,1.00,1.04\n"
                "2026-06-01T13:20:00-04:00,SPY   260612P00099000,1.00,1.04\n"
                "2026-06-01T13:50:00-04:00,SPY   260612C00101000,1.20,1.24\n",
                encoding="utf-8",
            )
            diagnostic = diagnose_file(
                path, bars, (signal,), "SPY", min_dte=7, max_dte=21,
                min_premium=.8, max_premium=10, max_spread_pct=.08,
                wait_minutes=1, hold_minutes=30,
            )[0]
        self.assertEqual(1, diagnostic.wrong_option_type)
        self.assertEqual(1, diagnostic.eligible_contracts)
        self.assertEqual("SPY   260612C00101000", diagnostic.selected_contract)
        self.assertTrue(diagnostic.exit_quote_found)
        self.assertEqual(0.0, diagnostic.first_exit_quote_delay_seconds)
        self.assertEqual(1.2, diagnostic.first_exit_bid)
        self.assertEqual(1.24, diagnostic.first_exit_ask)

    def test_measures_late_real_exit_quote_without_calling_it_an_exact_exit(self) -> None:
        bars = (
            Bar(datetime.fromisoformat("2026-06-01T13:19:00-04:00"), 100, 101, 99, 100, 1000),
            Bar(datetime.fromisoformat("2026-06-01T13:20:00-04:00"), 100, 101, 99, 100, 1000),
        )
        signal = Signal("TEST", Side.LONG, bars[0].timestamp, 100, 99, 102, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            path.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                "2026-06-01T13:20:00-04:00,SPY   260612C00101000,1.00,1.04\n"
                "2026-06-01T13:53:00-04:00,SPY   260612C00101000,1.20,1.24\n",
                encoding="utf-8",
            )
            diagnostic = diagnose_file(
                path, bars, (signal,), "SPY", min_dte=7, max_dte=21,
                min_premium=.8, max_premium=10, max_spread_pct=.08,
                wait_minutes=1, hold_minutes=30, exit_diagnostic_minutes=10,
            )[0]
        self.assertEqual("SPY   260612C00101000", diagnostic.selected_contract)
        self.assertFalse(diagnostic.exit_quote_found)
        self.assertEqual(180.0, diagnostic.first_exit_quote_delay_seconds)
        self.assertEqual(1.2, diagnostic.first_exit_bid)
        self.assertEqual(1.24, diagnostic.first_exit_ask)

    def test_reports_wide_quote_without_inventing_a_contract(self) -> None:
        bars = (
            Bar(datetime.fromisoformat("2026-06-01T13:19:00-04:00"), 100, 101, 99, 100, 1000),
            Bar(datetime.fromisoformat("2026-06-01T13:20:00-04:00"), 100, 101, 99, 100, 1000),
        )
        signal = Signal("TEST", Side.LONG, bars[0].timestamp, 100, 99, 102, {})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            path.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                "2026-06-01T13:20:00-04:00,SPY   260612C00101000,0.80,1.20\n",
                encoding="utf-8",
            )
            diagnostic = diagnose_file(
                path, bars, (signal,), "SPY", min_dte=7, max_dte=21,
                min_premium=.8, max_premium=10, max_spread_pct=.08,
                wait_minutes=1, hold_minutes=30,
            )[0]
        self.assertEqual(1, diagnostic.spread_too_wide)
        self.assertIsNone(diagnostic.selected_contract)
        self.assertFalse(diagnostic.exit_quote_found)

    def test_tracks_each_signal_when_the_same_contract_is_selected_twice(self) -> None:
        bars = (
            Bar(datetime.fromisoformat("2026-06-01T13:19:00-04:00"), 100, 101, 99, 100, 1000),
            Bar(datetime.fromisoformat("2026-06-01T13:20:00-04:00"), 100, 101, 99, 100, 1000),
            Bar(datetime.fromisoformat("2026-06-01T13:24:00-04:00"), 100, 101, 99, 100, 1000),
            Bar(datetime.fromisoformat("2026-06-01T13:25:00-04:00"), 100, 101, 99, 100, 1000),
        )
        signals = (
            Signal("TEST", Side.LONG, bars[0].timestamp, 100, 99, 102, {}),
            Signal("TEST", Side.LONG, bars[2].timestamp, 100, 99, 102, {}),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            path.write_text(
                "ts_recv,symbol,bid_px_00,ask_px_00\n"
                "2026-06-01T13:20:00-04:00,SPY   260612C00101000,1.00,1.04\n"
                "2026-06-01T13:25:00-04:00,SPY   260612C00101000,1.02,1.06\n"
                "2026-06-01T13:50:00-04:00,SPY   260612C00101000,1.20,1.24\n"
                "2026-06-01T13:55:00-04:00,SPY   260612C00101000,1.30,1.34\n",
                encoding="utf-8",
            )
            diagnostics = diagnose_file(
                path, bars, signals, "SPY", min_dte=7, max_dte=21,
                min_premium=.8, max_premium=10, max_spread_pct=.08,
                wait_minutes=1, hold_minutes=30,
            )
        self.assertEqual(2, len(diagnostics))
        self.assertTrue(all(item.exit_quote_found for item in diagnostics))
        self.assertEqual([1.2, 1.3], [item.first_exit_bid for item in diagnostics])


if __name__ == "__main__":
    unittest.main()
