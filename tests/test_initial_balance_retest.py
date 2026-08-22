from datetime import datetime, timedelta
import unittest

from research.engine.models import Bar, Side
from research.engine.strategies import InitialBalanceRetest


class InitialBalanceRetestTests(unittest.TestCase):
    def _bar(self, minute, open_, high, low, close):
        return Bar(datetime(2026, 1, 5, 9, 30) + timedelta(minutes=minute),
                   open_, high, low, close, 1000)

    def test_long_requires_separate_breakout_and_retest(self):
        bars = [self._bar(i * 5, 100, 101, 99, 100) for i in range(12)]
        bars.append(self._bar(60, 100.8, 101.5, 100.8, 101.4))
        bars.append(self._bar(65, 101.3, 101.5, 100.9, 101.35))
        strategy = InitialBalanceRetest()
        signal = None
        for index in range(len(bars)):
            signal = strategy.evaluate(bars[:index + 1]) or signal
        self.assertIsNotNone(signal)
        self.assertEqual(Side.LONG, signal.side)
        self.assertEqual("initial_balance_retest_v1_frozen", signal.features["rule_version"])

    def test_does_not_enter_on_breakout_bar(self):
        bars = [self._bar(i * 5, 100, 101, 99, 100) for i in range(12)]
        bars.append(self._bar(60, 100.8, 101.5, 100.8, 101.4))
        strategy = InitialBalanceRetest()
        signal = None
        for index in range(len(bars)):
            signal = strategy.evaluate(bars[:index + 1]) or signal
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
