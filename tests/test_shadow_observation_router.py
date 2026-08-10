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
    def test_adx_gated_observation_is_recorded_but_never_returned(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        observed: list[str] = []
        resolved: list[str] = []
        passthrough = lambda signals, *args, **kwargs: list(signals)
        gates = SimpleNamespace(
            apply_regime_gate=passthrough,
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
            ("INST_ORB", lambda _frame, ticker: _signal("INST_ORB")),
            ("FVG", lambda _frame, ticker: _signal("FVG")),
        ]), patch.object(router, "_gates", gates), patch.object(router, "compute_adx", return_value=0.0), patch(
            "shadow_ledger.resolve_due_directional_outcomes", return_value=None,
        ):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies={"FVG"},
                observation_only_strategies={"INST_ORB"}, quiet=True,
                prepared_today=frame,
                candidate_observer=lambda _ticker, signal, _price: observed.append(signal.strategy_id),
                observation_resolver=lambda signal: resolved.append(signal.strategy_id),
            )

        self.assertEqual(["INST_ORB", "FVG"], observed)
        self.assertEqual(["INST_ORB"], resolved)
        self.assertEqual(["FVG"], [signal.strategy_id for signal in returned])


if __name__ == "__main__":
    unittest.main()
