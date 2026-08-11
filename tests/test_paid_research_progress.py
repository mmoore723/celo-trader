from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from strategy_health.paid_research_progress import tsla_trend_exit_progress


class PaidResearchProgressTests(unittest.TestCase):
    def test_missing_report_is_safe_and_unavailable(self) -> None:
        result = tsla_trend_exit_progress(Path("/definitely/missing/report.json"))
        self.assertFalse(result["available"])

    def test_partial_study_is_provisional(self) -> None:
        with TemporaryDirectory() as directory:
            report = Path(directory) / "study.json"
            report.write_text(json.dumps({
                "ticker": "tsla", "strategy": "trend_continuation",
                "candidate_files": 10, "processed_files": ["a", "b", "c"], "complete": False,
                "selection": {"selected_hold_minutes": 60, "summaries": {"60": {"holdout": {"measured_signals": 0}}}},
            }))
            result = tsla_trend_exit_progress(report)
        self.assertTrue(result["available"])
        self.assertEqual(30.0, result["progress_pct"])
        self.assertEqual("testing_exit_clock", result["status"])
        self.assertEqual(60, result["provisional_exit_minutes"])

    def test_complete_study_requires_review_before_trading(self) -> None:
        with TemporaryDirectory() as directory:
            report = Path(directory) / "study.json"
            report.write_text(json.dumps({
                "candidate_files": 2, "processed_files": ["a", "b"], "complete": True,
                "selection": {"selected_hold_minutes": 60, "summaries": {"60": {"holdout": {"measured_signals": 12}}}},
            }))
            result = tsla_trend_exit_progress(report)
        self.assertEqual("review_pending", result["status"])
        self.assertIn("must still approve or reject", result["decision"])
