"""Regression checks for paid-study signal-to-paper parity."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

import strategy_router.route as router
from trading.v2_orb_execution_profile import uses_reviewed_paid_execution_profile


def _signal(strategy_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_id=strategy_id, direction="bullish", confidence=0.80,
        rvol=1.0, meta={}, trigger_bar="test",
    )


class ReviewedPaidExecutionProfileTests(unittest.TestCase):
    def test_only_reviewed_ids_receive_locked_execution_profile(self) -> None:
        self.assertTrue(uses_reviewed_paid_execution_profile("V2_ORB_PULLBACK"))
        self.assertTrue(uses_reviewed_paid_execution_profile("v2_spy_trend_cont"))
        self.assertFalse(uses_reviewed_paid_execution_profile("V2_TREND_CONT"))
        self.assertFalse(uses_reviewed_paid_execution_profile("MID_BRK"))

    def test_reviewed_spy_signal_skips_legacy_filters_only_when_requested(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0], "volume": [1.0, 1.0]})

        def must_not_run(*_args, **_kwargs):
            raise AssertionError("legacy quality filter ran for reviewed paid-data paper signal")

        gates = SimpleNamespace(
            apply_regime_gate=must_not_run,
            apply_session_bias_penalty=must_not_run,
            apply_vwap_weight=must_not_run,
            apply_confluence_bonus=must_not_run,
            apply_mtf_confirmation=must_not_run,
            apply_grade_filter=must_not_run,
            apply_large_move_gate=must_not_run,
            apply_directional_consensus=must_not_run,
            apply_confidence_floor=must_not_run,
            check_conflict_veto=must_not_run,
            check_volume_roc_veto=must_not_run,
        )
        with patch.object(router, "ACTIVE_STRATEGIES", [
            ("V2_SPY_TREND_CONT", lambda _frame, ticker: _signal("V2_SPY_TREND_CONT")),
        ]), patch.object(router, "_gates", gates), patch.object(router, "compute_adx", return_value=0.0):
            returned = router.route_signals(
                frame, "SPY", enabled_strategies={"V2_SPY_TREND_CONT"},
                quiet=True, prepared_today=frame,
                preserve_reviewed_paid_paper_rules=True,
            )

        self.assertEqual(["V2_SPY_TREND_CONT"], [signal.strategy_id for signal in returned])


if __name__ == "__main__":
    unittest.main()
