from datetime import datetime, time, timedelta
import unittest

from research.engine.models import Bar, Side
from research.engine.strategies.afternoon_compression_breakout import AfternoonCompressionBreakoutConfig
from research.engine.strategies.afternoon_compression_confirmation import (
    AfternoonCompressionConfirmation,
    AfternoonCompressionConfirmationConfig,
)


def bars_through_break() -> list[Bar]:
    start = datetime(2026, 5, 12, 12, 0)
    bars = [
        Bar(start + timedelta(minutes=index), close - .02, close + .04, close - .04, close, 1000)
        for index, close in enumerate((100.0, 100.1, 100.2, 100.25, 100.3, 100.35))
    ]
    box_start = datetime(2026, 5, 12, 12, 30)
    bars.extend(
        Bar(box_start + timedelta(minutes=index), close, 100.40, 100.32, close, 1000)
        for index, close in enumerate((100.35, 100.37, 100.36))
    )
    bars.append(Bar(datetime(2026, 5, 12, 12, 33), 100.38, 100.58, 100.36, 100.55, 1000))
    return bars


def config(mode: str) -> AfternoonCompressionConfirmationConfig:
    return AfternoonCompressionConfirmationConfig(
        breakout=AfternoonCompressionBreakoutConfig(
            fast_ema=3, slow_ema=5, atr_bars=3, min_compression_bars=3,
            compression_start=time(12, 30), compression_end=time(12, 33),
            entry_end=time(13, 0), max_compression_pct=.01,
        ),
        mode=mode,
    )


class AfternoonCompressionConfirmationTests(unittest.TestCase):
    def evaluate(self, strategy, bars):
        signal = None
        for index in range(1, len(bars) + 1):
            signal = strategy.evaluate(bars[:index]) or signal
        return signal

    def test_one_minute_hold_delays_signal_until_next_completed_bar(self) -> None:
        bars = bars_through_break()
        strategy = AfternoonCompressionConfirmation(config("hold_1m"))
        self.assertIsNone(self.evaluate(strategy, bars))
        bars.append(Bar(datetime(2026, 5, 12, 12, 34), 100.54, 100.62, 100.48, 100.60, 1000))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("afternoon_compression_hold_1m", signal.features["trigger"])

    def test_retest_requires_touch_and_close_back_outside_boundary(self) -> None:
        bars = bars_through_break()
        strategy = AfternoonCompressionConfirmation(config("retest_5m"))
        self.assertIsNone(self.evaluate(strategy, bars))
        bars.append(Bar(datetime(2026, 5, 12, 12, 34), 100.55, 100.65, 100.50, 100.62, 1000))
        self.assertIsNone(strategy.evaluate(bars))
        bars.append(Bar(datetime(2026, 5, 12, 12, 35), 100.61, 100.64, 100.39, 100.52, 1000))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual("retest_5m", signal.features["confirmation_mode"])

    def test_hold_variant_rejects_immediate_failed_break(self) -> None:
        bars = bars_through_break()
        strategy = AfternoonCompressionConfirmation(config("hold_1m"))
        self.assertIsNone(self.evaluate(strategy, bars))
        bars.append(Bar(datetime(2026, 5, 12, 12, 34), 100.50, 100.54, 100.30, 100.35, 1000))
        self.assertIsNone(strategy.evaluate(bars))


if __name__ == "__main__":
    unittest.main()
