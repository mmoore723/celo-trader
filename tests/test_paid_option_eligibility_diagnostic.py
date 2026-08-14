from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from research.engine.models import Bar, Side, Signal
from research.jobs.diagnose_paid_option_eligibility import diagnose_file


class PaidOptionEligibilityDiagnosticTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
