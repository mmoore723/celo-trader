from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import pandas as pd

import strategies.spy_afternoon_reversal_v2 as reversal
from strategies.market_structure import Bar


def _valid_bars() -> tuple[Bar, ...]:
    """A 5-minute SPY session with the paid-study reversal shape."""
    start = datetime(2026, 8, 10, 9, 30)
    prices: list[float] = []
    prices.extend(100.0 - 0.10 * index for index in range(11))       # Morning selloff.
    prices.extend(99.0 + 0.09 * index for index in range(14))        # Recovery.
    prices.extend((100.18, 100.05, 99.92, 99.80, 99.70, 99.80))      # Prior confirmed low.
    prices.extend((99.94, 100.08, 100.22, 100.37, 100.52, 100.38))  # Confirmed high.
    prices.extend((100.24, 100.12, 100.00, 100.12, 100.28))         # Higher low.
    prices.extend((100.44, 100.60, 100.78, 100.95, 100.80, 100.70, 100.62, 101.15))
    return tuple(
        Bar(
            start + timedelta(minutes=5 * index), price - 0.03,
            price + 0.08, price - 0.08, price, 1_000.0,
        )
        for index, price in enumerate(prices)
    )


class SpyAfternoonReversalV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        reversal._emitted_trigger_by_session.clear()

    def test_exact_long_only_reversal_emits_in_selected_window(self) -> None:
        candidate = reversal._signal_from_completed_bars(_valid_bars())

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual("V2_SPY_AFTERNOON_REVERSAL", candidate.strategy_id)
        self.assertEqual("bullish", candidate.direction)
        self.assertEqual("morning_selloff_higher_low_bos", candidate.meta["trigger"])
        self.assertEqual(13, candidate.trigger_bar.hour)
        self.assertEqual(35, candidate.trigger_bar.minute)

    def test_rule_rejects_outside_selected_hour(self) -> None:
        bars = _valid_bars()
        shifted = tuple(
            Bar(bar.timestamp + timedelta(hours=1), bar.open, bar.high, bar.low, bar.close, bar.volume)
            for bar in bars
        )
        self.assertIsNone(reversal._signal_from_completed_bars(shifted))

    def test_live_adapter_is_spy_only_and_emits_once_per_signal(self) -> None:
        frame = pd.DataFrame({
            "time": [datetime(2026, 8, 10, 13, 31)],
            "open": [101.1], "high": [101.2], "low": [101.0], "close": [101.1], "rvol": [1.2],
        })
        with patch.object(reversal, "_complete_five_minute_bars", return_value=_valid_bars()):
            self.assertIsNone(reversal.evaluate(frame, "QQQ"))
            first = reversal.evaluate(frame, "SPY")
            second = reversal.evaluate(frame, "SPY")

        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(1.2, first.rvol)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
