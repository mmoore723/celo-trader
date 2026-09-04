from __future__ import annotations

from datetime import datetime
import unittest

from trading.portfolio_policy import (
    SPY_TREND_MIN_ROOM_ATR,
    reviewed_portfolio_entry_policy,
    reviewed_strategy_entry_policy,
)


def _decision(hour, minute, *, ticker="SPY", strategy_id="V2_SPY_TREND_CONT", fvg_enabled=True):
    return reviewed_portfolio_entry_policy(
        ticker=ticker,
        strategy_id=strategy_id,
        now_et=datetime(2026, 8, 21, hour, minute),
        settings={"strategy_spy_afternoon_fvg_v2_enabled": fvg_enabled},
    )


class ReviewedPortfolioPolicyTests(unittest.TestCase):
    def test_spy_trend_is_allowed_before_selected_cutoff(self):
        self.assertTrue(_decision(13, 44).allowed)

    def test_spy_trend_is_reserved_during_selected_window(self):
        at_start = _decision(13, 45)
        self.assertFalse(at_start.allowed)
        self.assertFalse(_decision(15, 0).allowed)
        self.assertEqual("spy_afternoon_fvg_slot_reserved", at_start.reason_code)

    def test_spy_trend_is_allowed_after_fvg_window(self):
        self.assertTrue(_decision(15, 1).allowed)

    def test_rule_does_not_block_afternoon_fvg(self):
        self.assertTrue(_decision(14, 0, strategy_id="V2_SPY_AFTERNOON_FVG").allowed)

    def test_rule_does_not_block_other_tickers(self):
        self.assertTrue(_decision(14, 0, ticker="TSLA").allowed)

    def test_rule_is_inactive_when_afternoon_fvg_is_disabled(self):
        self.assertTrue(_decision(14, 0, fvg_enabled=False).allowed)

    def test_spy_trend_needs_room_before_resistance_for_calls(self):
        decision = reviewed_strategy_entry_policy(
            ticker="SPY",
            strategy_id="V2_SPY_TREND_CONT",
            direction="bullish",
            signal_meta={"pa_resistance_distance_atr": SPY_TREND_MIN_ROOM_ATR - 0.01},
        )
        self.assertFalse(decision.allowed)
        self.assertEqual("spy_trend_level_too_close", decision.reason_code)
        self.assertIn("resistance", decision.reason_detail)

    def test_spy_trend_needs_room_before_support_for_puts(self):
        decision = reviewed_strategy_entry_policy(
            ticker="SPY",
            strategy_id="V2_SPY_TREND_CONT",
            direction="bearish",
            signal_meta={"pa_support_distance_atr": 0.49},
        )
        self.assertFalse(decision.allowed)
        self.assertIn("support", decision.reason_detail)

    def test_spy_trend_allows_exact_threshold_or_no_detected_wall(self):
        at_threshold = reviewed_strategy_entry_policy(
            ticker="SPY",
            strategy_id="V2_SPY_TREND_CONT",
            direction="bullish",
            signal_meta={"pa_resistance_distance_atr": 0.50},
        )
        no_wall = reviewed_strategy_entry_policy(
            ticker="SPY",
            strategy_id="V2_SPY_TREND_CONT",
            direction="bearish",
            signal_meta={"pa_support_distance_atr": None},
        )
        self.assertTrue(at_threshold.allowed)
        self.assertTrue(no_wall.allowed)

    def test_entry_context_rule_does_not_block_research_tickers_or_other_strategies(self):
        metadata = {"pa_resistance_distance_atr": 0.01}
        self.assertTrue(reviewed_strategy_entry_policy(
            ticker="TSLA", strategy_id="V2_SPY_TREND_CONT",
            direction="bullish", signal_meta=metadata,
        ).allowed)
        self.assertTrue(reviewed_strategy_entry_policy(
            ticker="SPY", strategy_id="V2_SPY_AFTERNOON_FVG",
            direction="bullish", signal_meta=metadata,
        ).allowed)


if __name__ == "__main__":
    unittest.main()
