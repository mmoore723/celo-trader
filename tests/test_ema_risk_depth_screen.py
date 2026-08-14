import unittest

from research.jobs.screen_paid_tsla_ema_risk_depths import choose_depth


class EmaRiskDepthScreenTests(unittest.TestCase):
    def test_selection_uses_only_oldest_period(self):
        candidates = [
            {"minimum_risk_pct": .003,
             "selection": {"trades": 20, "average_return_pct": 1, "median_return_pct": 1, "profit_factor": 2},
             "validation": {"trades": 20, "average_return_pct": -20, "median_return_pct": -20, "profit_factor": 0},
             "later": {"trades": 20, "average_return_pct": -20, "median_return_pct": -20, "profit_factor": 0}},
            {"minimum_risk_pct": .008,
             "selection": {"trades": 20, "average_return_pct": 2, "median_return_pct": 2, "profit_factor": 3},
             "validation": {"trades": 20, "average_return_pct": 99, "median_return_pct": 99, "profit_factor": 99},
             "later": {"trades": 20, "average_return_pct": 99, "median_return_pct": 99, "profit_factor": 99}},
        ]
        self.assertEqual(.008, choose_depth(candidates)["minimum_risk_pct"])

    def test_nonpositive_selection_is_ineligible(self):
        candidate = {"minimum_risk_pct": .003,
                     "selection": {"trades": 20, "average_return_pct": 4, "median_return_pct": -1, "profit_factor": 2}}
        self.assertIsNone(choose_depth([candidate]))


if __name__ == "__main__":
    unittest.main()
