from __future__ import annotations

import unittest

from config.strategy_catalog import REVIEWED_STRATEGIES
from config.strategy_live_promotion import review_live_promotion


class StrategyLivePromotionTests(unittest.TestCase):
    def test_repaired_underpowered_policy_is_not_mistaken_for_live_readiness(self) -> None:
        review = review_live_promotion(REVIEWED_STRATEGIES["V2_SPY_TREND_CONT"])
        self.assertFalse(review.ready)
        self.assertEqual("shadow_observation", review.stage)
        self.assertTrue(any("promising underpowered" in reason for reason in review.blockers))
        self.assertTrue(any("19/30" in reason for reason in review.blockers))
        self.assertTrue(any("Prospective shadow evidence" in reason for reason in review.blockers))
        self.assertTrue(any("Broker execution gate failed" in reason for reason in review.blockers))

    def test_inconsistent_historical_candidate_explains_that_blocker(self) -> None:
        review = review_live_promotion(REVIEWED_STRATEGIES["V2_ORB_PULLBACK"])
        self.assertFalse(review.ready)
        self.assertTrue(any("promising inconsistent" in reason for reason in review.blockers))


if __name__ == "__main__":
    unittest.main()
