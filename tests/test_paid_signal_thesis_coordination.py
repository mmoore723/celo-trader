from datetime import date
import unittest

from research.jobs.evaluate_paid_signal_thesis_coordination import (
    apply_reentry_cooldown,
    build_report,
    decision_time_clusters,
)


def row(strategy, entry, exit_time, side="LONG", pnl=10.0):
    ask = 1.0
    bid = ask + pnl / 100
    return {
        "strategy_id": strategy,
        "ticker": "SPY",
        "evidence_grade": "passed_declared_holdout",
        "signal_time": entry,
        "entry_time": entry,
        "exit_time": exit_time,
        "entry_ask": ask,
        "exit_bid": bid,
        "return_pct": (bid - ask) / ask * 100,
        "side": side,
        "contract": "SPY   260821C00500000",
    }


class PaidSignalThesisCoordinationTests(unittest.TestCase):
    def test_only_exactly_simultaneous_signals_are_rankable(self):
        rows = [
            row("A", "2026-07-01T14:00:00+00:00", "2026-07-01T14:05:00+00:00"),
            row("B", "2026-07-01T14:00:00+00:00", "2026-07-01T14:05:00+00:00"),
            row("C", "2026-07-01T14:01:00+00:00", "2026-07-01T14:06:00+00:00"),
        ]
        clusters = decision_time_clusters(rows)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(
            {item["strategy_id"] for item in clusters[0]},
            {"A", "B"},
        )

    def test_cooldown_does_not_block_opposite_direction(self):
        rows = [
            row("A", "2026-07-01T14:00:00+00:00", "2026-07-01T14:05:00+00:00", "LONG"),
            row("B", "2026-07-01T14:10:00+00:00", "2026-07-01T14:15:00+00:00", "SHORT"),
            row("C", "2026-07-01T14:12:00+00:00", "2026-07-01T14:17:00+00:00", "LONG"),
        ]
        kept, removed = apply_reentry_cooldown(rows, minutes=15)
        self.assertEqual([item["strategy_id"] for item in kept], ["A", "B"])
        self.assertEqual([item["strategy_id"] for item in removed], ["C"])

    def test_report_cannot_pass_without_causal_overlap_sample(self):
        rows = [
            row("A", "2026-06-01T14:00:00+00:00", "2026-06-01T14:05:00+00:00"),
            row("B", "2026-07-01T14:00:00+00:00", "2026-07-01T14:05:00+00:00"),
        ]
        report = build_report(rows, holdout_start=date(2026, 7, 1))
        self.assertFalse(report["decision"]["passed"])
        self.assertFalse(report["decision"]["runtime_changed"])
        self.assertFalse(
            report["decision"]["gates"][
                "at_least_20_causal_multi_strategy_decisions"
            ]
        )


if __name__ == "__main__":
    unittest.main()
