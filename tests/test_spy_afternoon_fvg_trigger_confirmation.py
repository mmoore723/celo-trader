from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from research.jobs.audit_spy_afternoon_fvg_trigger_confirmation import (
    _net_pnl, _passes,
    trigger_context,
)
from strategies.market_structure import Bar


def _minute_bars() -> tuple[Bar, ...]:
    start = datetime(2026, 5, 1, 9, 30)
    bars = []
    for index in range(25 * 5):
        bucket = index // 5
        price = 100.0 + bucket * 0.10
        bars.append(Bar(
            start + timedelta(minutes=index), price, price + 0.04,
            price - 0.04, price, 1_000.0,
        ))
    # The final minute in the latest 5m bucket closes sharply below the fast
    # EMA.  A prior-bucket bug would miss this contradiction.
    latest = bars[-1]
    bars[-1] = Bar(
        latest.timestamp, latest.open, latest.high, latest.low - 0.70,
        latest.close - 0.60, latest.volume,
    )
    return tuple(bars)


class SpyAfternoonFvgTriggerConfirmationTests(unittest.TestCase):
    def test_context_includes_trigger_bucket_labeled_by_its_last_minute(self) -> None:
        bars = _minute_bars()
        row = {"signal_time": bars[-1].timestamp.isoformat(), "side": "long"}

        context = trigger_context(row, bars)

        self.assertLess(context.close_to_fast_ema_atr, 0.0)
        self.assertFalse(_passes("close_on_fast_ema_side", row, context))

    def test_fast_ema_gate_is_symmetric(self) -> None:
        class Context:
            close_to_fast_ema_atr = -0.2
            close_location = 0.2

        self.assertFalse(_passes("close_on_fast_ema_side", {"side": "long"}, Context()))
        self.assertTrue(_passes("close_on_fast_ema_side", {"side": "short"}, Context()))
        self.assertFalse(_passes("decisive_close_60_40", {"side": "long"}, Context()))
        self.assertTrue(_passes("decisive_close_60_40", {"side": "short"}, Context()))

    def test_net_pnl_uses_adverse_slippage_and_current_fee_model(self) -> None:
        self.assertAlmostEqual(6.70, _net_pnl({"entry_ask": 5.00, "exit_bid": 5.10}))


if __name__ == "__main__":
    unittest.main()
