import unittest

from research.jobs.evaluate_reviewed_strategy_selector import simulate_policy


def candidate(
    strategy: str, ticker: str, minute: int, *, return_pct: float,
    exit_minute: int | None = None, grade: str = "passed_declared_holdout",
    ask: float = 1.0,
) -> dict[str, object]:
    exit_at = exit_minute if exit_minute is not None else minute + 1
    bid = ask * (1 + return_pct / 100)
    return {
        "strategy_id": strategy,
        "ticker": ticker,
        "evidence_grade": grade,
        "signal_time": f"2026-01-02T10:{minute:02d}:00-05:00",
        "entry_time": f"2026-01-02T10:{minute:02d}:00-05:00",
        "exit_time": f"2026-01-02T10:{exit_at:02d}:00-05:00",
        "entry_ask": ask,
        "exit_bid": bid,
        "return_pct": return_pct,
    }


class ReviewedStrategySelectorTests(unittest.TestCase):
    def test_future_win_cannot_change_an_earlier_quality_decision(self):
        history = [candidate("A", "SPY", minute, return_pct=-10) for minute in range(10)]
        rejected = candidate("A", "SPY", 20, return_pct=-5)
        future_win = candidate("A", "SPY", 30, return_pct=500)
        base = simulate_policy(
            history + [rejected], policy="causal_trailing_quality",
            minimum_history=10, trailing_window=20,
        )
        with_future = simulate_policy(
            history + [rejected, future_win], policy="causal_trailing_quality",
            minimum_history=10, trailing_window=20,
        )
        base_decision = next(row for row in base["skipped"] if row["entry_time"] == rejected["entry_time"])
        future_decision = next(row for row in with_future["skipped"] if row["entry_time"] == rejected["entry_time"])
        self.assertEqual("trailing_quality", base_decision["skip_reason"])
        self.assertEqual(base_decision["quality_at_decision"], future_decision["quality_at_decision"])

    def test_one_position_per_ticker_blocks_overlap(self):
        first = candidate("A", "SPY", 0, return_pct=10, exit_minute=10)
        overlap = candidate("B", "SPY", 1, return_pct=10, exit_minute=2)
        result = simulate_policy([first, overlap], policy="all_affordable")
        self.assertEqual(1, len(result["accepted"]))
        self.assertEqual("ticker_position_open", result["skipped"][0]["skip_reason"])

    def test_unaffordable_candidate_does_not_take_slot(self):
        expensive = candidate("A", "TSLA", 0, return_pct=10, ask=8.0)
        affordable = candidate("B", "SPY", 1, return_pct=10, ask=1.0)
        result = simulate_policy(
            [expensive, affordable], policy="all_affordable",
            max_positions=1, starting_capital=5_000, allocation_fraction=.15,
        )
        self.assertEqual(["B"], [row["strategy_id"] for row in result["accepted"]])
        self.assertEqual("unaffordable", result["skipped"][0]["skip_reason"])

    def test_evidence_grade_breaks_simultaneous_same_ticker_tie(self):
        weaker = candidate(
            "WEAK", "SPY", 0, return_pct=10, exit_minute=5,
            grade="promising_inconsistent",
        )
        stronger = candidate(
            "STRONG", "SPY", 0, return_pct=10, exit_minute=5,
            grade="passed_declared_holdout",
        )
        result = simulate_policy([weaker, stronger], policy="all_affordable")
        self.assertEqual("STRONG", result["accepted"][0]["strategy_id"])
        self.assertEqual("ticker_position_open", result["skipped"][0]["skip_reason"])


if __name__ == "__main__":
    unittest.main()
