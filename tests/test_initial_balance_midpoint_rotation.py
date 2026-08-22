from datetime import datetime, timedelta
import unittest

from research.engine.models import Bar, Side
from research.engine.strategies.initial_balance_midpoint_rotation import InitialBalanceMidpointRotation


def bar(at, open_, high, low, close, volume=1_000):
    return Bar(at, open_, high, low, close, volume)


class InitialBalanceMidpointRotationTest(unittest.TestCase):
    def test_short_rotation_uses_midpoint_invalidation(self):
        start = datetime(2026, 8, 3, 9, 30)
        bars = [
            bar(start + timedelta(minutes=5 * i), *values)
            for i, values in enumerate([
                (105, 106, 100, 101), (101, 104, 100, 103),
                (103, 107, 102, 106), (106, 110, 105, 109),
                (109, 110, 106, 108), (108, 109, 106, 108),
            ])
        ]
        strategy = InitialBalanceMidpointRotation()
        self.assertIsNone(strategy.evaluate(bars))
        bars.append(bar(datetime(2026, 8, 3, 10, 0), 108, 109, 107, 108.5))
        self.assertIsNone(strategy.evaluate(bars))
        bars.append(bar(datetime(2026, 8, 3, 10, 5), 106, 106, 103, 104))
        signal = strategy.evaluate(bars)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, Side.SHORT)
        self.assertAlmostEqual(signal.stop, 106)
        self.assertAlmostEqual(signal.target, 100)
        self.assertGreaterEqual(signal.features["planned_reward_risk"], 1.25)


if __name__ == "__main__":
    unittest.main()
