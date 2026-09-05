from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

import pandas as pd

from trading.position_manager.manage import (
    _clear_exit_latch,
    _evaluate_reviewed_strategy_exit,
    _exit_latch_snapshot,
    _resolve_latched_exit,
)


class ExitLatchTests(unittest.TestCase):
    def test_exit_stays_active_when_next_tick_condition_disappears(self) -> None:
        state: dict = {}
        fired_at = datetime(2026, 8, 21, 10, 30)

        self.assertEqual(
            (True, "vwap_and_trend_breakdown"),
            _resolve_latched_exit(state, True, "vwap_and_trend_breakdown", fired_at),
        )
        self.assertEqual(
            (True, "vwap_and_trend_breakdown"),
            _resolve_latched_exit(
                state, False, "hold", fired_at + timedelta(minutes=1),
            ),
        )
        self.assertEqual(fired_at.isoformat(), state["exit_pending_since"])

    def test_hold_does_not_create_an_exit_latch(self) -> None:
        state: dict = {}
        self.assertEqual(
            (False, "hold"),
            _resolve_latched_exit(state, False, "hold", datetime(2026, 8, 21, 10, 30)),
        )
        self.assertNotIn("exit_pending_reason", state)

    def test_normal_position_snapshot_preserves_pending_exit(self) -> None:
        self.assertEqual(
            {
                "exit_pending_reason": "vwap_and_trend_breakdown",
                "exit_pending_since": "2026-08-21T10:30:00",
                "exit_attempts": 3,
            },
            _exit_latch_snapshot({
                "exit_pending_reason": "vwap_and_trend_breakdown",
                "exit_pending_since": "2026-08-21T10:30:00",
                "exit_attempts": 3,
            }),
        )

    def test_completed_partial_profit_take_clears_old_exit_intent(self) -> None:
        state = {
            "exit_pending_reason": "stage1_profit_take",
            "exit_pending_since": "2026-08-21T10:30:00",
            "exit_attempts": 2,
            "stage1_done": True,
        }
        _clear_exit_latch(state)
        self.assertNotIn("exit_pending_reason", state)
        self.assertNotIn("exit_pending_since", state)
        self.assertEqual(0, state["exit_attempts"])
        self.assertTrue(state["stage1_done"])

    def test_position_manager_routes_vwap_displacement_to_structural_exit(self) -> None:
        entry = datetime.fromisoformat("2026-09-03T10:31:00-04:00")
        one_minute = pd.DataFrame([
            {
                "time": "2026-09-03 10:32:00",
                "high": 101.20,
                "low": 100.50,
                "close": 101.00,
                "volume": 1000,
            },
        ])
        result = _evaluate_reviewed_strategy_exit(
            {
                "strategy_id": "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
                "strategy_context_json": json.dumps({"previous_high": 101.0}),
            },
            entry,
            datetime.fromisoformat("2026-09-03T10:33:00-04:00"),
            one_minute_bars=one_minute,
            five_minute_bars=None,
        )

        self.assertEqual((True, "vwap_displacement_prior_high_target"), result)

    def test_position_manager_retains_fixed_exit_for_other_reviewed_strategy(self) -> None:
        entry = datetime.fromisoformat("2026-09-03T10:00:00-04:00")
        result = _evaluate_reviewed_strategy_exit(
            {"strategy_id": "V2_SPY_TREND_CONT"},
            entry,
            entry + timedelta(minutes=30),
            one_minute_bars=None,
            five_minute_bars=None,
        )

        self.assertEqual(
            (True, "v2_spy_trend_paid_markout_30m (held=30.0min)"),
            result,
        )

    def test_unreviewed_strategy_stays_in_adaptive_exit_manager(self) -> None:
        result = _evaluate_reviewed_strategy_exit(
            {"strategy_id": "INST_ORB"},
            datetime(2026, 9, 3, 10, 0),
            datetime(2026, 9, 3, 10, 30),
            one_minute_bars=None,
            five_minute_bars=None,
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
