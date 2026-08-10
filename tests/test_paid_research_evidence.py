import unittest

from strategy_health.paid_research_evidence import v2_orb_tsla_summary


class PaidResearchEvidenceTests(unittest.TestCase):
    def test_rejected_plain_orb_is_explicitly_distinct_from_v2(self) -> None:
        summary = v2_orb_tsla_summary()
        rejected = summary["rejected_comparison"]
        self.assertLess(rejected["average_return_pct"], 0)
        self.assertNotEqual(rejected["label"], summary["label"])
        self.assertIn("not a generic ORB", rejected["interpretation"])


if __name__ == "__main__":
    unittest.main()
