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
             patch.object(router, "_authorized_for_order", return_value=True), \
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
        ), patch.object(router, "_authorized_for_order", return_value=True):
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

    def test_out_of_execution_scope_strategy_still_runs_as_shadow_only(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        calls: list[tuple[str, str]] = []
        observed: list[str] = []

        def evaluate(_frame, ticker="", execution_scope=None):
            calls.append((ticker, execution_scope))
            return _signal("V2_SPY_TREND_CONT")

        with patch.object(router, "ACTIVE_STRATEGIES", [("V2_SPY_TREND_CONT", evaluate)]), \
             patch.object(router, "compute_adx", return_value=30.0), \
             patch.object(router, "_authorized_for_order", return_value=False), \
             patch("auth.context.get_current_user_id", return_value="account-a"), \
             patch("shadow_ledger.resolve_due_directional_outcomes", return_value=None):
            returned = router.route_signals(
                frame, "AAPL", enabled_strategies=set(),
                observation_only_strategies={"V2_SPY_TREND_CONT"}, quiet=True,
                prepared_today=frame,
                candidate_observer=lambda _ticker, signal, _price: observed.append(signal.strategy_id),
                observation_resolver=lambda _signal: None,
            )

        self.assertEqual([("SPY", "cross_ticker_shadow:account-a:AAPL")], calls)
        self.assertEqual(["V2_SPY_TREND_CONT"], observed)
        self.assertEqual([], returned)

    def test_out_of_execution_scope_order_strategy_remains_blocked(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        calls: list[str] = []
        with patch.object(router, "ACTIVE_STRATEGIES", [
            ("V2_SPY_TREND_CONT", lambda _frame, ticker: calls.append(ticker) or _signal("V2_SPY_TREND_CONT")),
        ]), patch.object(router, "compute_adx", return_value=30.0), \
             patch.object(router, "_authorized_for_order", return_value=False):
            returned = router.route_signals(
                frame, "AAPL", enabled_strategies={"V2_SPY_TREND_CONT"},
                quiet=True, prepared_today=frame,
            )
        self.assertEqual([], calls)
        self.assertEqual([], returned)

    def test_injected_strategy_runs_without_a_dummy_bar_evaluator(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        injected = _signal("V2_ORB_PULLBACK")
        with patch.object(router, "ACTIVE_STRATEGIES", []), \
             patch.object(router, "compute_adx", return_value=30.0), \
             patch.object(router, "_authorized_for_order", return_value=True):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies={"V2_ORB_PULLBACK"}, quiet=True,
                prepared_today=frame, injected_signals=[injected],
                preserve_reviewed_paid_rules=True,
            )
        self.assertEqual([injected], returned)

    def test_disabled_injected_strategy_is_discarded(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        with patch.object(router, "ACTIVE_STRATEGIES", []), \
             patch.object(router, "compute_adx", return_value=30.0):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies=set(), quiet=True,
                prepared_today=frame, injected_signals=[_signal("V2_ORB_PULLBACK")],
            )
        self.assertEqual([], returned)

    def test_observation_only_injected_strategy_never_returns_to_entry(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        resolved: list[str] = []
        with patch.object(router, "ACTIVE_STRATEGIES", []), \
             patch.object(router, "compute_adx", return_value=30.0), \
             patch("shadow_ledger.resolve_due_directional_outcomes", return_value=None):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies=set(),
                observation_only_strategies={"V2_ORB_PULLBACK"}, quiet=True,
                prepared_today=frame, injected_signals=[_signal("V2_ORB_PULLBACK")],
                candidate_observer=lambda *_args: None,
                observation_resolver=lambda signal: resolved.append(signal.strategy_id),
            )
        self.assertEqual(["V2_ORB_PULLBACK"], resolved)
        self.assertEqual([], returned)

    def test_catalog_observer_cannot_be_forced_into_order_set(self) -> None:
        frame = pd.DataFrame({"close": [100.0, 101.0]})
        strategy_id = "CTX_ORB_NR7_OR_INSIDE"
        observed: list[str] = []
        resolved: list[str] = []
        with patch.object(router, "ACTIVE_STRATEGIES", [
            (strategy_id, lambda _frame, ticker: _signal(strategy_id)),
        ]), patch.object(router, "compute_adx", return_value=30.0), \
             patch.object(router, "_authorized_for_order", return_value=True), \
             patch("shadow_ledger.resolve_due_directional_outcomes", return_value=None):
            returned = router.route_signals(
                frame, "TSLA", enabled_strategies={strategy_id}, quiet=True,
                prepared_today=frame,
                candidate_observer=lambda _ticker, signal, _price: observed.append(signal.strategy_id),
                observation_resolver=lambda signal: resolved.append(signal.strategy_id),
            )
        self.assertEqual([strategy_id], observed)
        self.assertEqual([strategy_id], resolved)
        self.assertEqual([], returned)


if __name__ == "__main__":
    unittest.main()
