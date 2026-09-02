from datetime import datetime, timedelta
import unittest

from research.engine.models import Bar
from research.jobs.assess_spy_trend_qqq_confirmation import qqq_confirms


def bars(direction: int):
    start = datetime.fromisoformat("2026-05-12T09:30:00-04:00")
    output = []
    price = 400.0
    for index in range(30):
        next_price = price + direction * 0.10
        output.append(Bar(start + timedelta(minutes=index), price,
                          max(price, next_price) + .01, min(price, next_price) - .01,
                          next_price, 1000))
        price = next_price
    return output


class QqqConfirmationTests(unittest.TestCase):
    def test_long_requires_all_three_bullish_conditions(self):
        session = bars(1)
        row = {"signal_time": session[-1].timestamp.isoformat(), "side": "long"}
        result = qqq_confirms(row, {session[-1].timestamp.date(): session})
        self.assertIsNotNone(result)
        self.assertTrue(result[0])

    def test_short_rejects_bullish_qqq_context(self):
        session = bars(1)
        row = {"signal_time": session[-1].timestamp.isoformat(), "side": "short"}
        self.assertFalse(qqq_confirms(row, {session[-1].timestamp.date(): session})[0])

    def test_future_bars_are_not_visible(self):
        session = bars(1)
        signal = session[24].timestamp
        # Reverse sharply only after the decision. A causal join still sees
        # the earlier rising context and therefore confirms the long.
        future = []
        price = session[-1].close
        for index in range(30, 36):
            future.append(Bar(session[0].timestamp + timedelta(minutes=index), price,
                              price + .01, price - 1.01, price - 1.0, 1000))
            price -= 1.0
        row = {"signal_time": signal.isoformat(), "side": "long"}
        self.assertTrue(qqq_confirms(row, {signal.date(): session + future})[0])


if __name__ == "__main__":
    unittest.main()
