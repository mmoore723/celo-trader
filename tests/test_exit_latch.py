from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from trading.position_manager.manage import (
    _clear_exit_latch,
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


if __name__ == "__main__":
    unittest.main()
