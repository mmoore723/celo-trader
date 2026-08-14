import unittest
from datetime import datetime, timedelta

from ai_reasoning.calibration import evaluate_ai_gate_policy


def episodes(*, ai_improvement: float, days: int = 30) -> list[dict]:
    start = datetime.fromisoformat("2026-06-01T10:00:00-04:00")
    rows = []
    for index in range(60):
        baseline = -2.0 if index % 2 == 0 else 1.0
        action = "veto" if index % 2 == 0 else "approve"
        policy = (0.0 if action == "veto" else baseline) + ai_improvement
        rows.append({
            "observed_at": (start + timedelta(days=index % days, minutes=index)).isoformat(),
            "action": action, "baseline_return_pct": baseline,
            "policy_return_pct": policy,
        })
    return rows


class AiGateCalibrationTests(unittest.TestCase):
    def test_requires_real_independent_option_evidence(self):
        result = evaluate_ai_gate_policy(episodes(ai_improvement=1.0)[:20])
        self.assertEqual("collecting_option_outcomes", result["status"])
        self.assertFalse(result["recommended_for_enforcement"])

    def test_passes_only_when_earlier_and_later_data_improve(self):
        result = evaluate_ai_gate_policy(episodes(ai_improvement=1.0))
        self.assertEqual("validated_candidate", result["status"])
        self.assertTrue(result["checks"]["training_improved"])
        self.assertTrue(result["checks"]["holdout_improved"])
        self.assertTrue(result["recommended_for_enforcement"])

    def test_rejects_training_only_improvement(self):
        rows = episodes(ai_improvement=1.0)
        for row in sorted(rows, key=lambda item: item["observed_at"])[-12:]:
            row["policy_return_pct"] = row["baseline_return_pct"] - 0.5
        result = evaluate_ai_gate_policy(rows)
        self.assertEqual("failed_chronological_validation", result["status"])
        self.assertFalse(result["checks"]["holdout_improved"])
        self.assertFalse(result["recommended_for_enforcement"])

    def test_requires_both_veto_and_approval_evidence(self):
        rows = episodes(ai_improvement=1.0)
        for row in rows:
            row["action"] = "approve"
        result = evaluate_ai_gate_policy(rows)
        self.assertEqual("collecting_action_balance", result["status"])


if __name__ == "__main__":
    unittest.main()
