from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from strategies.base import Signal
from trading.cross_ticker_shadow import evaluate_bar_strategy, update_orb, update_two_leg


def _signal(strategy_id: str) -> Signal:
    return Signal(
        strategy_id=strategy_id, direction="bullish", confidence=0.8,
        rvol=1.0, trigger_bar=pd.Timestamp("2026-08-21 10:00:00"), meta={},
    )


class CrossTickerShadowTests(unittest.TestCase):
    def test_bar_adapter_uses_validated_alias_and_isolated_actual_ticker_scope(self) -> None:
        calls = []

        def evaluator(frame, ticker="", execution_scope=None):
            calls.append((frame, ticker, execution_scope))
            return _signal("V2_SPY_TREND_CONT")

        frame = pd.DataFrame({"close": [100.0]})
        result = evaluate_bar_strategy(
            "V2_SPY_TREND_CONT", evaluator, frame,
            ticker="AAPL", account_scope="acct-1",
        )
        self.assertIsNotNone(result)
        self.assertIs(calls[0][0], frame)
        self.assertEqual("SPY", calls[0][1])
        self.assertEqual("cross_ticker_shadow:acct-1:AAPL", calls[0][2])

    def test_unknown_strategy_cannot_enter_shadow_adapter(self) -> None:
        self.assertIsNone(evaluate_bar_strategy(
            "LEGACY", lambda *_args, **_kwargs: _signal("LEGACY"),
            pd.DataFrame(), ticker="AAPL", account_scope="acct-1",
        ))

    @patch("trading.orb_retouch_execution.update_one_minute_orb_retouch")
    def test_orb_adapter_preserves_actual_state_but_calls_locked_tsla_rule(self, reviewed) -> None:
        reviewed.return_value = (None, "waiting")
        state = {}
        now = datetime(2026, 8, 21, 10, 0)
        update_orb(state, pd.DataFrame(), ticker="AAPL", quote_price=10.0, now=now)
        self.assertIs(reviewed.call_args.args[0], state)
        self.assertEqual("TSLA", reviewed.call_args.kwargs["ticker"])

    @patch("trading.two_leg_trend_pullback_execution.update_two_leg_trend_pullback")
    def test_two_leg_adapter_calls_locked_tsla_rule(self, reviewed) -> None:
        reviewed.return_value = (None, "waiting")
        state = {}
        now = datetime(2026, 8, 21, 10, 0)
        update_two_leg(state, pd.DataFrame(), ticker="AAPL", now=now)
        self.assertIs(reviewed.call_args.args[0], state)
        self.assertEqual("TSLA", reviewed.call_args.kwargs["ticker"])


if __name__ == "__main__":
    unittest.main()
