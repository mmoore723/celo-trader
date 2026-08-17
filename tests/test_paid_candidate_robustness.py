import unittest

from research.jobs.assess_paid_candidate_robustness import read_dotted


class PaidCandidateRobustnessTests(unittest.TestCase):
    def test_reads_nested_markout_list(self):
        payload = {"comparable": {"fixed": [{"return_pct": 2.0}]}}
        self.assertEqual(
            read_dotted(payload, "comparable.fixed"),
            [{"return_pct": 2.0}],
        )

    def test_rejects_missing_markout_list(self):
        with self.assertRaisesRegex(ValueError, "has no"):
            read_dotted({"comparable": {}}, "comparable.fixed")


if __name__ == "__main__":
    unittest.main()
