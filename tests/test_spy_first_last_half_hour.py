from datetime import datetime
import unittest

from research.jobs.screen_spy_first_last_half_hour import select


class FirstLastHalfHourTests(unittest.TestCase):
    def test_later_period_cannot_select_the_floor(self):
        candidates = [
            {"minimum_opening_move_pct": 0.0,
             "selection": {"trades": 9, "average_return_pct": 1, "median_return_pct": 1, "profit_factor": 2},
             "later": {"trades": 20, "average_return_pct": -99}},
            {"minimum_opening_move_pct": .2,
             "selection": {"trades": 9, "average_return_pct": .5, "median_return_pct": .5, "profit_factor": 1.5},
             "later": {"trades": 20, "average_return_pct": 99}},
        ]
        self.assertEqual(0.0, select(candidates)["minimum_opening_move_pct"])

    def test_negative_selection_median_is_rejected(self):
        candidate = {"minimum_opening_move_pct": .1,
                     "selection": {"trades": 20, "average_return_pct": 1, "median_return_pct": -1, "profit_factor": 2}}
        self.assertIsNone(select([candidate]))


if __name__ == "__main__":
    unittest.main()
