"""Descriptions must follow the execution policy, not unused reference stops."""
import copy
import unittest
from unittest.mock import patch

import pandas as pd

from trading.diagnostics.exit_policy import reviewed_exit_description
from trading.diagnostics.bar_thinking import _log_bar_thinking
from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
from trading.v2_orb_paper_exit import V2_EXIT_MINUTES_BY_STRATEGY


class ExitPolicyNarrationTests(unittest.TestCase):
    def setUp(self):
        self.now = pd.Timestamp("2026-09-18 10:45", tz="America/New_York")
        self.trade = {"id": 1, "strategy_id": "V2_SPY_TREND_CONT", "ticker": "SPY",
                      "entry_time": "2026-09-18T10:30:00-04:00", "entry_price": 5,
                      "contracts": 2, "option_type": "call"}
        self.position = {"current_option_price": 4.50, "current_stop_pct": .20,
                         "stage1_done": True, "struct_stop_price": 4.30}

    def test_catalog_timers_match_all_reviewed_timed_strategies(self):
        for strategy, minutes in V2_EXIT_MINUTES_BY_STRATEGY.items():
            if uses_v2_orb_execution_profile(strategy):
                with self.subTest(strategy=strategy):
                    result = reviewed_exit_description({**self.trade, "strategy_id": strategy}, self.position, self.now)
                    self.assertIn(f"{minutes}-minute timer", result)
                    self.assertIn("do not control this trade", result)
                    self.assertNotIn("Stage 2", result)
                    self.assertNotIn("4.30", result)

    def test_elapsed_clock_and_remaining(self):
        result = reviewed_exit_description(self.trade, self.position, self.now)
        self.assertIn("15.0/30 minutes held, 15.0 minutes left", result)

    def test_utc_and_naive_et_are_consistent(self):
        expected = reviewed_exit_description(self.trade, self.position, self.now)
        for entry in ("2026-09-18T14:30:00+00:00", "2026-09-18T10:30:00"):
            self.assertEqual(expected, reviewed_exit_description({**self.trade, "entry_time": entry}, self.position, self.now.tz_convert("UTC")))

    def test_position_entry_clock_takes_precedence_like_manager(self):
        result = reviewed_exit_description(self.trade, {**self.position, "entry_time": "2026-09-18 10:40"}, self.now)
        self.assertIn("5.0/30 minutes held", result)

    def test_due_timer_is_not_a_claim_of_fill(self):
        for minute in (30, 35):
            result = reviewed_exit_description(self.trade, self.position, self.now + pd.Timedelta(minutes=minute-15))
            self.assertIn("close is due, not yet confirmed", result)
            self.assertNotIn("minutes left", result)

    def test_missing_and_invalid_entry_times_do_not_invent_a_countdown(self):
        for entry in (None, "", "broken", "NaT"):
            result = reviewed_exit_description({**self.trade, "entry_time": entry}, self.position, self.now)
            self.assertIn("Entry time unavailable", result)

    def test_pending_close_overrides_holding_narrative(self):
        result = reviewed_exit_description(self.trade, {**self.position, "exit_pending_reason": "daily_loss"}, self.now)
        self.assertIn("Exit requested: daily_loss", result)
        self.assertIn("Waiting for the broker", result)
        self.assertNotIn("minutes left", result)

    def test_structural_strategy_is_not_given_fixed_timer(self):
        result = reviewed_exit_description({**self.trade, "strategy_id": "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"}, self.position, self.now)
        self.assertIn("5-minute close below VWAP", result)
        self.assertIn("90-minute fallback", result)
        self.assertNotIn("90-minute timer", result)

    def test_generic_strategy_keeps_existing_path(self):
        self.assertIsNone(reviewed_exit_description({**self.trade, "strategy_id": "OTHER"}, self.position, self.now))

    def test_normalization_and_no_mutation(self):
        trade = {**self.trade, "strategy_id": " v2_spy_trend_cont "}
        before = copy.deepcopy((trade, self.position))
        self.assertIn("30-minute timer", reviewed_exit_description(trade, self.position, self.now))
        self.assertEqual(before, (trade, self.position))

    def test_thinking_panel_logs_actual_policy_and_negative_pnl(self):
        bars = pd.DataFrame({"time": pd.date_range("2026-09-18 10:43", periods=2, freq="min"),
                             "open": [600, 600], "high": [601, 601], "low": [599, 599],
                             "close": [600, 600], "volume": [1000, 1000]})
        state = {"open_trades": [self.trade], "positions": {1: self.position}}
        with patch("trading.diagnostics.bar_thinking.get_user_state", return_value=state), \
             patch("trading.diagnostics.bar_thinking._now_et", return_value=self.now), \
             patch("trading.diagnostics.bar_thinking.get_user_risk") as risk, \
             patch("signals.get_opening_range", return_value={}), \
             patch("database.log_event") as log:
            _log_bar_thinking(bars, bars, "SPY")
            log.assert_called_once()
            message = log.call_args.args[2]
            self.assertIn("30-minute timer", message)
            self.assertIn("$-100.00", message)
            self.assertNotIn("Stage 1", message)
            self.assertNotIn("Stop $", message)
            risk.assert_not_called()
            _log_bar_thinking(bars, bars, "SPY")
            log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
