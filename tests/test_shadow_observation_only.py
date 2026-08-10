"""Regression tests for paper-only, non-ordering strategy observations."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shadow_ledger import mark_candidate_observed_only


class ShadowObservationOnlyTests(unittest.TestCase):
    def test_observed_signal_is_resolved_without_a_trade(self) -> None:
        signal = SimpleNamespace(meta={"shadow_candidate_id": "candidate-1"})
        with patch("shadow_ledger.resolve_candidate_from_context") as resolve:
            mark_candidate_observed_only(signal)
        resolve.assert_called_once_with(
            {"strategy_meta": signal.meta}, "observed_only", "not_approved_for_entry",
            "Paper-only observation; this strategy was never allowed to place an order.", None,
        )


if __name__ == "__main__":
    unittest.main()
