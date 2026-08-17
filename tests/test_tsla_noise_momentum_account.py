import unittest
from datetime import date

from research.jobs.evaluate_tsla_noise_momentum_account import (
    STRATEGY_ID,
    build_report,
)


def row(day: int, *, return_pct: float, ask: float = 1.0) -> dict[str, object]:
    bid = ask * (1 + return_pct / 100)
    return {
        "strategy_id": STRATEGY_ID,
        "ticker": "TSLA",
        "evidence_grade": "passed_declared_holdout",
        "signal_time": f"2026-06-{day:02d}T10:00:00-04:00",
        "entry_time": f"2026-06-{day:02d}T10:01:00-04:00",
        "exit_time": f"2026-06-{day:02d}T15:59:00-04:00",
        "entry_ask": ask,
        "exit_bid": bid,
        "return_pct": return_pct,
    }


class TslaNoiseMomentumAccountTests(unittest.TestCase):
    def test_rejects_when_later_segment_is_missing(self):
        candidates = [row(day, return_pct=5) for day in range(1, 31)]
        report = build_report(candidates, holdout_start=date(2026, 7, 1))
        self.assertFalse(report["decision"]["account_screen_passed"])

    def test_whole_contract_affordability_is_reported(self):
        candidates = [row(day, return_pct=5, ask=9.0) for day in range(1, 31)]
        report = build_report(candidates, holdout_start=date(2026, 7, 1))
        self.assertGreater(report["primary"]["skip_counts"].get("unaffordable", 0), 0)


if __name__ == "__main__":
    unittest.main()
