import unittest

from api.routes.learning import (
    CATEGORY_TARGETS, _coach_copy, _collapse_independent_episodes,
    _decision_bar_index, _eligible_recorded_row, _example_category,
    _practice_eligible,
)


class LearningExampleTests(unittest.TestCase):
    def row(self, **updates):
        base = {
            "candidate_id": "candidate-1",
            "strategy_id": "V2_SPY_TREND_CONT",
            "direction": "bullish",
            "final_outcome": "observed_only",
            "gate_reason": None,
            "gate_detail": None,
            "direction_correct": None,
            "directional_move_pct": None,
            "outcome_observed_at": None,
        }
        return {**base, **updates}

    def test_declared_mix_contains_fifty_examples(self):
        self.assertEqual(50, sum(CATEGORY_TARGETS.values()))
        self.assertEqual(15, CATEGORY_TARGETS["clean_win"])
        self.assertEqual(10, CATEGORY_TARGETS["valid_loss"])

    def test_measured_direction_classifies_win_and_loss(self):
        self.assertEqual(
            "clean_win",
            _example_category(self.row(direction_correct=1, outcome_observed_at="2026-08-21T10:30:00-04:00")),
        )
        self.assertEqual(
            "valid_loss",
            _example_category(self.row(direction_correct=0, outcome_observed_at="2026-08-21T10:30:00-04:00")),
        )

    def test_recorded_gate_reason_wins_over_unmeasured_outcome(self):
        row = self.row(
            final_outcome="blocked",
            gate_reason="relative_volume",
            gate_detail="Relative volume was below the reviewed minimum",
        )
        self.assertEqual("rejected_missing_condition", _example_category(row))

    def test_chop_reason_has_its_own_teaching_bucket(self):
        row = self.row(final_outcome="blocked", gate_reason="market_structure", gate_detail="Chop around VWAP")
        self.assertEqual("false_breakout_or_chop", _example_category(row))

    def test_unresolved_episode_is_not_labeled_a_win_or_loss(self):
        self.assertEqual("ambiguous_no_trade", _example_category(self.row()))

    def test_coach_copy_is_grounded_in_recorded_reason(self):
        row = self.row(
            final_outcome="blocked",
            gate_reason="relative_volume",
            gate_detail="Relative volume was below the reviewed minimum",
        )
        copy = _coach_copy(row, _example_category(row))
        self.assertIn("Relative volume was below", copy["summary"])
        self.assertNotIn("guarantee", copy["prompt"].lower())

    def test_repeated_minute_detections_are_one_learning_episode(self):
        rows = [
            {**self.row(), "candidate_id": "first", "observed_at": "2026-08-21T10:00:00-04:00"},
            {**self.row(direction_correct=1, outcome_observed_at="2026-08-21T10:30:00-04:00"), "candidate_id": "repeat", "observed_at": "2026-08-21T10:08:00-04:00"},
            {**self.row(), "candidate_id": "new", "observed_at": "2026-08-21T10:30:00-04:00"},
        ]
        episodes = _collapse_independent_episodes(rows)
        self.assertEqual(2, len(episodes))
        self.assertEqual("repeat", episodes[0]["candidate_id"])
        self.assertEqual(2, episodes[0]["episode_size"])
        self.assertEqual(1, episodes[0]["direction_correct"])

    def test_decision_bar_never_uses_a_future_candle(self):
        # Candle storage is timezone-naive ET; candidate timestamps are aware.
        bars = [{"time": f"2026-08-21T10:0{minute}:00"} for minute in range(4)]
        self.assertEqual(1, _decision_bar_index(bars, "2026-08-21T10:01:30-04:00"))
        self.assertEqual(0, _decision_bar_index(bars, "2026-08-21T09:59:00-04:00"))

    def test_examples_require_recorded_version_and_reviewed_ticker(self):
        row = self.row(ticker="SPY", metadata_json='{"strategy_version":"2.0.0"}')
        self.assertTrue(_eligible_recorded_row(row))
        self.assertFalse(_eligible_recorded_row({**row, "ticker": "QQQ"}))
        self.assertFalse(_eligible_recorded_row({**row, "metadata_json": "{}"}))

    def test_operational_blocks_are_not_scored_as_chart_decisions(self):
        operational = self.row(gate_reason="daily_lock", gate_detail="Daily loss limit active")
        chart_gate = self.row(gate_reason="relative_volume", gate_detail="RVOL below minimum")
        self.assertFalse(_practice_eligible(operational, "rejected_missing_condition"))
        self.assertTrue(_practice_eligible(chart_gate, "rejected_missing_condition"))


if __name__ == "__main__":
    unittest.main()
