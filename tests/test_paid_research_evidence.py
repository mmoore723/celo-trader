import unittest

from strategy_health.paid_research_evidence import v2_orb_tsla_summary


class PaidResearchEvidenceTests(unittest.TestCase):
    def test_rejected_plain_orb_is_explicitly_distinct_from_v2(self) -> None:
        summary = v2_orb_tsla_summary()
        rejected = summary["rejected_comparison"]
        self.assertLess(rejected["average_return_pct"], 0)
        self.assertNotEqual(rejected["label"], summary["label"])
        self.assertIn("not a generic ORB", rejected["interpretation"])

    def test_rejected_vwap_entry_is_explicit_about_its_holdout(self) -> None:
        summary = v2_orb_tsla_summary()
        rejected = summary["rejected_vwap_strategy"]
        self.assertEqual(395, rejected["measured_signals"])
        self.assertLess(rejected["average_return_pct"], 0)
        self.assertEqual(140, rejected["holdout_measured_signals"])
        self.assertLess(rejected["holdout_average_return_pct"], 0)
        self.assertIn("separate entry strategy", rejected["interpretation"])


if __name__ == "__main__":
    unittest.main()
