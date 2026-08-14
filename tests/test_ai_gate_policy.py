import unittest

from ai_reasoning.gate_policy import (
    AI_DECISION_ENFORCED_STRATEGY_IDS,
    ai_decision_effect,
    ai_decision_is_enforced,
)


class AiGatePolicyTests(unittest.TestCase):
    def test_unvalidated_ai_opinions_are_observation_only(self) -> None:
        self.assertEqual(frozenset(), AI_DECISION_ENFORCED_STRATEGY_IDS)
        for strategy_id in (
            "V2_ORB_PULLBACK", "V2_SPY_TREND_CONT",
            "V2_SPY_AFTERNOON_FVG", "V2_TSLA_TWO_LEG_TREND_PULLBACK",
        ):
            self.assertFalse(ai_decision_is_enforced(strategy_id))

    def test_unvalidated_veto_and_resize_cannot_change_order(self) -> None:
        self.assertEqual(("observe", 4), ai_decision_effect("V2_ORB_PULLBACK", "veto", 0, 4))
        self.assertEqual(("observe", 4), ai_decision_effect("V2_ORB_PULLBACK", "reduce_size", .25, 4))

    def test_approve_never_changes_order(self) -> None:
        self.assertEqual(("approve", 3), ai_decision_effect("ANY", "approve", 9, 3))


if __name__ == "__main__":
    unittest.main()
