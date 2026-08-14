"""Ensure paper-only learning candidates cannot become order candidates."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

import strategy_router.route as router


def _signal(strategy_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_id=strategy_id, direction="bullish", confidence=0.8,
        rvol=1.5, meta={}, trigger_bar="test",
    )


class ShadowObservationRouterTests(unittest.TestCase):
    def test_candidate_link_survives_a_gate_that_copies_the_signal(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        original = _signal("V2_SPY_AFTERNOON_FVG")

        def copy_without_meta(signals, *args, **kwargs):
            return [SimpleNamespace(**{**signal.__dict__, "meta": {}}) for signal in signals]

        passthrough = lambda signals, *args, **kwargs: list(signals)
        gates = SimpleNamespace(
            apply_session_bias_penalty=passthrough, apply_vwap_weight=passthrough,
            apply_confluence_bonus=passthrough, apply_mtf_confirmation=passthrough,
            apply_grade_filter=passthrough, apply_large_move_gate=passthrough,
            apply_directional_consensus=passthrough, apply_confidence_floor=passthrough,
            check_conflict_veto=lambda *args, **kwargs: False,
            check_volume_roc_veto=lambda *args, **kwargs: False,
        )

        def observe(_ticker, signal, _price):
            signal.meta["shadow_candidate_id"] = "candidate-123"

        with patch.object(router, "ACTIVE_STRATEGIES", [("V2_SPY_AFTERNOON_FVG", lambda _frame, ticker: original)]), \
             patch.object(router, "_gates", gates), patch.object(router, "compute_adx", return_value=30.0), \
             patch("shadow_ledger.resolve_due_directional_outcomes", return_value=None):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies={"V2_SPY_AFTERNOON_FVG"}, quiet=True,
                prepared_today=frame, candidate_observer=observe,
            )

        self.assertEqual("candidate-123", returned[0].meta["shadow_candidate_id"])

    def test_observation_only_strategy_is_recorded_but_never_returned(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        observed: list[str] = []
        resolved: list[str] = []
        passthrough = lambda signals, *args, **kwargs: list(signals)
        gates = SimpleNamespace(
            apply_session_bias_penalty=passthrough,
            apply_vwap_weight=passthrough,
            apply_confluence_bonus=passthrough,
            apply_mtf_confirmation=passthrough,
            apply_grade_filter=passthrough,
            apply_large_move_gate=passthrough,
            apply_directional_consensus=passthrough,
            apply_confidence_floor=passthrough,
            check_conflict_veto=lambda *args, **kwargs: False,
            check_volume_roc_veto=lambda *args, **kwargs: False,
        )
        with patch.object(router, "ACTIVE_STRATEGIES", [
            ("V2_ORB_PULLBACK", lambda _frame, ticker: _signal("V2_ORB_PULLBACK")),
            ("V2_SPY_TREND_CONT", lambda _frame, ticker: _signal("V2_SPY_TREND_CONT")),
        ]), patch.object(router, "_gates", gates), patch.object(router, "compute_adx", return_value=0.0), patch(
            "shadow_ledger.resolve_due_directional_outcomes", return_value=None,
        ):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies={"V2_SPY_TREND_CONT"},
                observation_only_strategies={"V2_ORB_PULLBACK"}, quiet=True,
                prepared_today=frame,
                candidate_observer=lambda _ticker, signal, _price: observed.append(signal.strategy_id),
                observation_resolver=lambda signal: resolved.append(signal.strategy_id),
            )

        self.assertEqual(["V2_ORB_PULLBACK", "V2_SPY_TREND_CONT"], observed)
        self.assertEqual(["V2_ORB_PULLBACK"], resolved)
        self.assertEqual(["V2_SPY_TREND_CONT"], [signal.strategy_id for signal in returned])


if __name__ == "__main__":
    unittest.main()
