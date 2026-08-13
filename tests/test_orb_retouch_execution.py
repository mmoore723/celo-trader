"""One-minute ORB retouch timing regression tests."""
from __future__ import annotations

from datetime import datetime
import unittest

import pandas as pd

from trading.orb_retouch_execution import update_one_minute_orb_retouch


def frame(closes: list[float], highs: list[float], lows: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.date_range("2026-01-02 09:30", periods=len(closes), freq="min"),
        "open": closes, "high": highs, "low": lows, "close": closes,
        "volume": [1000] * len(closes), "rvol": [1.2] * len(closes),
    })


class OneMinuteOrbRetouchTests(unittest.TestCase):
    def test_long_retouch_enters_on_quote_not_later_candle_close(self) -> None:
        closes = [100.0] * 15 + [101.0]
        highs = [100.5] * 15 + [101.2]
        lows = [99.5] * 15 + [100.8]
        state: dict[str, object] = {}
        signal, status = update_one_minute_orb_retouch(
            state, frame(closes, highs, lows), ticker="TSLA", quote_price=101.0,
            now=datetime(2026, 1, 2, 9, 47),
        )
        self.assertIsNone(signal)
        self.assertEqual("armed_waiting_for_first_retouch", status)

        # 100.53 is inside the 0.05% retouch zone around the 100.50 range high.
        signal, status = update_one_minute_orb_retouch(
            state, frame(closes, highs, lows), ticker="TSLA", quote_price=100.53,
            now=datetime(2026, 1, 2, 9, 47, 12),
        )
        self.assertEqual("first_retouch_quote", status)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("bullish", signal.direction)
        self.assertEqual("completed_1m_breakout_then_live_quote_first_retouch", signal.meta["entry_timing"])
        self.assertEqual(100.53, signal.meta["quote_entry_reference"])

    def test_breakout_that_falls_through_range_is_not_a_retouch_entry(self) -> None:
        closes = [100.0] * 15 + [101.0]
        highs = [100.5] * 15 + [101.2]
        lows = [99.5] * 15 + [100.8]
        state: dict[str, object] = {}
        signal, status = update_one_minute_orb_retouch(
            state, frame(closes, highs, lows), ticker="TSLA", quote_price=100.40,
            now=datetime(2026, 1, 2, 9, 48),
        )
        self.assertIsNone(signal)
        self.assertEqual("failed_retouch", status)

    def test_opening_range_requires_all_fifteen_one_minute_bars(self) -> None:
        state: dict[str, object] = {}
        signal, status = update_one_minute_orb_retouch(
            state, frame([100.0] * 14, [100.5] * 14, [99.5] * 14), ticker="TSLA",
            quote_price=100.5, now=datetime(2026, 1, 2, 9, 44),
        )
        self.assertIsNone(signal)
        self.assertEqual("building_or_waiting_for_breakout", status)

    def test_current_forming_minute_cannot_confirm_a_breakout(self) -> None:
        closes = [100.0] * 15 + [101.0]
        highs = [100.5] * 15 + [101.2]
        lows = [99.5] * 15 + [100.8]
        state: dict[str, object] = {}
        # At 09:45:20, the row labelled 09:45 is still forming and must not
        # arm a breakout.  It becomes eligible on the next minute boundary.
        signal, status = update_one_minute_orb_retouch(
            state, frame(closes, highs, lows), ticker="TSLA", quote_price=101.0,
            now=datetime(2026, 1, 2, 9, 45, 20),
        )
        self.assertIsNone(signal)
        self.assertEqual("building_or_waiting_for_breakout", status)

    def test_short_first_break_is_not_recast_as_a_later_long_setup(self) -> None:
        closes = [100.0] * 15 + [99.0]
        highs = [100.5] * 15 + [99.2]
        lows = [99.5] * 15 + [98.8]
        state: dict[str, object] = {}
        signal, status = update_one_minute_orb_retouch(
            state, frame(closes, highs, lows), ticker="TSLA", quote_price=99.5,
            now=datetime(2026, 1, 2, 9, 47),
        )
        self.assertIsNone(signal)
        self.assertEqual("outside_validated_direction", status)
        self.assertEqual("outside_validated_direction", state["terminal"])

    def test_retouch_window_expires_at_1030_eastern(self) -> None:
        closes = [100.0] * 15 + [101.0]
        highs = [100.5] * 15 + [101.2]
        lows = [99.5] * 15 + [100.8]
        state: dict[str, object] = {}
        signal, status = update_one_minute_orb_retouch(
            state, frame(closes, highs, lows), ticker="TSLA", quote_price=100.53,
            now=datetime(2026, 1, 2, 10, 31),
        )
        self.assertIsNone(signal)
        self.assertEqual("entry_window_expired", status)
        self.assertEqual("entry_window_expired", state["terminal"])


if __name__ == "__main__":
    unittest.main()
