from datetime import datetime, timedelta
import unittest

from strategies.market_structure import Bar
from strategies.price_action_context import describe_price_action


def bar(index, open_, high, low, close):
    return Bar(datetime(2026, 1, 2, 9, 30) + timedelta(minutes=index), open_, high, low, close)


class PriceActionContextTests(unittest.TestCase):
    def test_bullish_engulfing_and_momentum_are_directional(self):
        bars = [bar(0, 10.4, 10.5, 9.9, 10.0), bar(1, 9.95, 10.7, 9.9, 10.65)]
        context = describe_price_action(bars, atr=.5, fast_ema=10.2, slow_ema=10.1, vwap=10.0)
        self.assertTrue(context.bullish_engulfing)
        self.assertTrue(context.momentum_long)
        self.assertFalse(context.momentum_short)
        self.assertGreater(context.close_to_vwap_atr, 0)

    def test_rejection_and_inside_bar_labels(self):
        rejection = describe_price_action([bar(0, 10, 10.2, 9.0, 10.1)], atr=.5)
        inside = describe_price_action(
            [bar(0, 10, 11, 9, 10.5), bar(1, 10.2, 10.8, 9.4, 10.3)], atr=.5,
        )
        self.assertTrue(rejection.bullish_rejection)
        self.assertTrue(inside.inside_bar)

    def test_only_confirmed_pivots_are_used(self):
        bars = [
            bar(0, 10, 10.2, 9.8, 10), bar(1, 10, 10.4, 9.9, 10.2),
            bar(2, 10.2, 11.0, 10.1, 10.8), bar(3, 10.8, 10.9, 10.3, 10.5),
            bar(4, 10.5, 10.7, 10.2, 10.4), bar(5, 10.4, 12.0, 10.3, 11.5),
        ]
        context = describe_price_action(bars, atr=.5, pivot_wing=2)
        # Bar 2 is confirmed by bars 3 and 4; the latest high at bar 5 cannot
        # become resistance because no future bars exist to confirm it.
        self.assertIsNone(context.nearest_resistance)
        self.assertNotEqual(context.nearest_resistance, 12.0)

    def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            describe_price_action([], atr=1)

    def test_extended_single_and_two_candle_patterns(self):
        hammer = describe_price_action([
            bar(0, 10, 10.2, 9.8, 9.9), bar(1, 9.9, 10.02, 9.0, 9.98),
        ], atr=1)
        self.assertTrue(hammer.hammer)
        harami = describe_price_action([
            bar(0, 10.8, 11.0, 9.7, 9.8), bar(1, 9.9, 10.7, 9.85, 10.5),
        ], atr=1)
        self.assertTrue(harami.bullish_harami)

    def test_extended_three_candle_patterns(self):
        morning = describe_price_action([
            bar(0, 11, 11.1, 9.8, 10), bar(1, 9.95, 10.05, 9.8, 9.96),
            bar(2, 10, 10.8, 9.95, 10.7),
        ], atr=1)
        self.assertTrue(morning.morning_star)
        soldiers = describe_price_action([
            bar(0, 10, 10.5, 9.9, 10.4), bar(1, 10.3, 10.8, 10.2, 10.7),
            bar(2, 10.6, 11.1, 10.5, 11.0),
        ], atr=1)
        self.assertTrue(soldiers.three_white_soldiers)
        with self.assertRaises(ValueError):
            describe_price_action([bar(0, 10, 10, 10, 10)], atr=0)


if __name__ == "__main__":
    unittest.main()
