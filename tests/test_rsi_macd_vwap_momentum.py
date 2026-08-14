from datetime import datetime, timedelta
import unittest

from research.engine.models import Bar
from research.engine.strategies.rsi_macd_vwap_momentum import (
    RSIMACDVWAPMomentum, RSIMACDVWAPMomentumConfig,
)


class RSIMACDVWAPMomentumTests(unittest.TestCase):
    def test_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            RSIMACDVWAPMomentumConfig(long_rsi=49)

    def test_requires_sequential_completed_bars(self):
        strategy = RSIMACDVWAPMomentum()
        start = datetime(2026, 1, 5, 9, 30)
        bars = [Bar(start + timedelta(minutes=5 * index), 100, 101, 99, 100, 1000)
                for index in range(2)]
        strategy.evaluate(bars[:1])
        with self.assertRaisesRegex(ValueError, "sequential"):
            strategy.evaluate(bars[:1])

    def test_flat_market_emits_no_signal(self):
        strategy = RSIMACDVWAPMomentum()
        start = datetime(2026, 1, 5, 9, 30)
        history = []
        signals = []
        for index in range(61):
            history.append(Bar(start + timedelta(minutes=5 * index), 100, 100.1, 99.9, 100, 1000))
            signals.append(strategy.evaluate(history))
        self.assertFalse(any(signals))


if __name__ == "__main__":
    unittest.main()
