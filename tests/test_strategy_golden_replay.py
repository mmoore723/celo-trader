import unittest

from strategy_health.strategy_replay import replay_strategies


def bar_event(ticker="AMZN"):
    payload = {
        "timeframe": "1Min", "bar_time": "2026-08-26T09:30:00-04:00",
        "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000,
    }
    return {"kind": "market_bar", "ticker": ticker, "strategy_id": None,
            "timestamp": payload["bar_time"], "payload": payload}


class StrategyGoldenReplayTests(unittest.TestCase):
    def test_every_reviewed_strategy_is_checked_on_every_observed_ticker(self):
        result = replay_strategies([bar_event()])
        self.assertEqual(5, len(result["strategy_ticker_checks"]))
        self.assertEqual(["AMZN"], result["tickers_replayed"])
        orb = next(row for row in result["strategy_ticker_checks"]
                   if row["strategy_id"] == "V2_ORB_PULLBACK")
        self.assertEqual("missing_underlying_quote_tape", orb["status"])
        self.assertFalse(result["complete"])

    def test_quote_tape_makes_intraminute_strategy_comparable(self):
        quote = {
            "kind": "underlying_quote", "ticker": "AMZN", "strategy_id": None,
            "timestamp": "2026-08-26T09:31:00-04:00",
            "payload": {"mid": 100.5},
        }
        result = replay_strategies([bar_event(), quote])
        self.assertTrue(result["complete"])
        self.assertTrue(result["passed"])

    def test_repeated_replay_does_not_leave_strategy_dedupe_state(self):
        from strategies import spy_trend_continuation_v2 as trend
        before = set(trend._emitted_trigger_by_session)
        replay_strategies([bar_event("SPY")])
        replay_strategies([bar_event("SPY")])
        self.assertEqual(before, set(trend._emitted_trigger_by_session))


if __name__ == "__main__":
    unittest.main()
