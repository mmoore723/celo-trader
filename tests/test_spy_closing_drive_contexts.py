from datetime import datetime
import unittest

from research.jobs.screen_spy_closing_drive_contexts import select


def result(trades=8, average=1.0, median=1.0, pf=2.0):
    return {"trades": trades, "average_return_pct": average,
            "median_return_pct": median, "profit_factor": pf}


class ClosingDriveContextTests(unittest.TestCase):
    def test_later_data_cannot_select_variant(self):
        summaries = {
            "base": {"selection": result(median=2), "later": result(average=-99)},
            "afternoon_persistent": {"selection": result(median=1), "later": result(average=99)},
            "vwap_aligned": {"selection": result(median=-1), "later": result()},
            "persistent_and_vwap": {"selection": result(trades=2), "later": result()},
        }
        self.assertEqual("base", select(summaries))

    def test_negative_selection_median_is_not_eligible(self):
        summaries = {name: {"selection": result(median=-1)} for name in (
            "base", "afternoon_persistent", "vwap_aligned", "persistent_and_vwap")}
        self.assertIsNone(select(summaries))


if __name__ == "__main__":
    unittest.main()
