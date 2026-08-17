import unittest
from datetime import date

from research.jobs.evaluate_spy_strategy_portfolio import (
    FVG_ID,
    TREND_ID,
    build_report,
)


def candidate(
    strategy: str, day: int, minute: int, return_pct: float,
) -> dict[str, object]:
    ask = 1.0
    return {
        "strategy_id": strategy,
        "ticker": "SPY",
        "evidence_grade": (
            "passed_declared_holdout" if strategy == TREND_ID else "promising_underpowered"
        ),
        "signal_time": f"2026-07-{day:02d}T10:{minute:02d}:00-04:00",
        "entry_time": f"2026-07-{day:02d}T10:{minute:02d}:00-04:00",
        "exit_time": f"2026-07-{day:02d}T10:{minute + 1:02d}:00-04:00",
        "entry_ask": ask,
        "exit_bid": ask * (1 + return_pct / 100),
        "return_pct": return_pct,
    }


class SpyStrategyPortfolioTests(unittest.TestCase):
    def test_combined_report_keeps_overlapping_spy_trade_out(self):
        trend = [candidate(TREND_ID, 1, 0, 5)]
        fvg = [candidate(FVG_ID, 1, 0, 8)]
        report = build_report(trend, fvg, holdout_start=date(2026, 7, 1))
        combined = report["runs"]["combined"]
        self.assertEqual(1, combined["segments"]["later"]["trades"])
        self.assertEqual(1, combined["skip_counts"]["ticker_position_open"])
        self.assertEqual(1, combined["accepted_later_by_strategy"][TREND_ID])
        self.assertEqual(0, combined["accepted_later_by_strategy"][FVG_ID])

    def test_report_does_not_claim_ready_without_required_sample(self):
        trend = [candidate(TREND_ID, day, 0, 5) for day in range(1, 6)]
        fvg = [candidate(FVG_ID, day, 10, 5) for day in range(1, 6)]
        report = build_report(trend, fvg, holdout_start=date(2026, 7, 1))
        self.assertFalse(report["decision"]["integration_ready"])
        self.assertFalse(report["decision"]["gates"]["combined_later_at_least_20_trades"])


if __name__ == "__main__":
    unittest.main()
