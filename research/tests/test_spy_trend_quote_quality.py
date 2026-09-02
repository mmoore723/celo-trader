from datetime import date
import unittest

from research.jobs.assess_spy_trend_quote_quality import (
    GATES, MIN_COVERAGE, _candidate_passes, evaluate,
)


def row(day: int, pnl: float, spread: float = .005, ask: float = 5.0, money: float = .001):
    return {
        "signal_time": f"2026-06-{day:02d}T10:00:00-04:00" if day <= 30 else f"2026-07-{day-30:02d}T10:00:00-04:00",
        "return_pct": pnl,
        "pnl_at_cap": pnl,
        "spread_pct": spread,
        "entry_ask": ask,
        "moneyness_pct": money,
        "dte": 7,
    }


class SpyTrendQuoteQualityTests(unittest.TestCase):
    def test_frozen_gates_use_only_entry_time_fields(self):
        value = row(1, 10, spread=.0066)
        self.assertFalse(GATES["spread_at_most_65bp"](value))
        self.assertTrue(GATES["spread_at_most_75bp"](value))

    def test_candidate_gate_requires_high_coverage_and_better_drawdown(self):
        candidate = {"average_return_pct": 1, "median_return_pct": .5, "profit_factor": 1.5, "max_drawdown_at_cap": 80}
        baseline = {"max_drawdown_at_cap": 100}
        self.assertTrue(_candidate_passes(candidate, baseline, 20, 25, 20))
        self.assertFalse(_candidate_passes(candidate, baseline, 19, 25, 20))
        self.assertEqual(MIN_COVERAGE, .80)

    def test_later_period_cannot_select_a_gate(self):
        # Early data makes 65bp eligible. Later data is deliberately poor, so
        # it can reject the selected rule but cannot select a different one.
        rows = [row(day, 2, spread=.005) for day in range(1, 26)]
        rows += [row(day, -2, spread=.005) for day in range(31, 56)]
        report = evaluate(rows, date(2026, 7, 1))
        self.assertIsNotNone(report["selected_gate"])
        self.assertFalse(report["later_passed"])
        self.assertEqual(report["decision"], "retain_unfiltered_reviewed_entries")

    def test_filter_cannot_win_by_discarding_most_trades(self):
        rows = [row(day, 2, spread=.009) for day in range(1, 26)]
        for day in range(1, 5):
            rows[day - 1]["spread_pct"] = .005
        report = evaluate(rows, date(2026, 7, 1))
        self.assertIsNone(report["selected_gate"])


if __name__ == "__main__":
    unittest.main()
