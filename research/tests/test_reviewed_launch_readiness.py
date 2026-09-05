from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from research.jobs.evaluate_reviewed_launch_readiness import build_report
from research.jobs.evaluate_reviewed_strategy_selector import simulate_policy


STRATEGIES = (
    "V2_SPY_FAILED_RANGE_RECOVERY",
    "V2_SPY_TREND_CONT",
    "V2_SPY_AFTERNOON_FVG",
    "V2_ORB_PULLBACK",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
)


def candidate(
    strategy: str, ticker: str, minute: int, *, return_pct: float,
    exit_minute: int | None = None,
) -> dict[str, object]:
    exit_at = exit_minute if exit_minute is not None else minute + 1
    ask = 1.0
    return {
        "strategy_id": strategy,
        "ticker": ticker,
        "evidence_grade": "passed_declared_holdout",
        "signal_time": f"2026-01-02T10:{minute:02d}:00-05:00",
        "entry_time": f"2026-01-02T10:{minute:02d}:00-05:00",
        "exit_time": f"2026-01-02T10:{exit_at:02d}:00-05:00",
        "entry_ask": ask,
        "exit_bid": ask * (1 + return_pct / 100),
        "return_pct": return_pct,
    }


def rows(start: datetime, count: int, return_pct: float) -> list[dict]:
    output = []
    for index in range(count):
        strategy_id = STRATEGIES[index % len(STRATEGIES)]
        signal = start + timedelta(days=index)
        entry = signal + timedelta(minutes=1)
        output.append({
            "strategy_id": strategy_id,
            "ticker": "SPY" if strategy_id.startswith("V2_SPY") else "TSLA",
            "evidence_grade": "passed_declared_holdout",
            "signal_time": signal.isoformat(),
            "entry_time": entry.isoformat(),
            "exit_time": (entry + timedelta(minutes=30)).isoformat(),
            "entry_ask": 1.0,
            "exit_bid": 1.0 + return_pct / 100,
            "return_pct": return_pct,
        })
    return output


def strategy_rows(
    strategy_id: str, ticker: str, start: datetime, returns: list[float],
) -> list[dict]:
    output = []
    for index, return_pct in enumerate(returns):
        signal = start + timedelta(days=index)
        entry = signal + timedelta(minutes=1)
        output.append({
            "strategy_id": strategy_id,
            "ticker": ticker,
            "evidence_grade": "passed_declared_holdout",
            "signal_time": signal.isoformat(),
            "entry_time": entry.isoformat(),
            "exit_time": (entry + timedelta(minutes=30)).isoformat(),
            "entry_ask": 1.0,
            "exit_bid": 1.0 + return_pct / 100,
            "return_pct": return_pct,
        })
    return output


class ReviewedLaunchReadinessTests(unittest.TestCase):
    def test_trailing_quality_requires_the_1_5_launch_target(self) -> None:
        history = [
            candidate("A", "SPY", minute, return_pct=(10 if minute < 6 else -12))
            for minute in range(10)
        ]
        decision = candidate("A", "SPY", 20, return_pct=10)
        result = simulate_policy(
            history + [decision], policy="causal_trailing_quality",
            minimum_history=10, trailing_window=20,
        )
        rejected = next(row for row in result["skipped"] if row["entry_time"] == decision["entry_time"])
        self.assertEqual("trailing_quality", rejected["skip_reason"])
        self.assertEqual(1.25, rejected["quality_at_decision"]["profit_factor"])

    def test_cost_model_charges_subscription_once_and_both_execution_sides(self) -> None:
        payload = [
            candidate("A", "SPY", 0, return_pct=10),
            candidate("B", "TSLA", 2, return_pct=10),
        ]
        result = simulate_policy(
            payload, policy="all_affordable", starting_capital=5_000,
            allocation_fraction=.15, per_contract_fee_per_side=1.0,
            slippage_price_per_side=.01, monthly_subscription=10.0,
        )
        self.assertEqual(5_074.0, result["ending_cash"])
        self.assertEqual(56.0, result["cost_model"]["transaction_costs"])
        self.assertEqual(10.0, result["cost_model"]["subscription_costs"])
        self.assertEqual(["2026-01"], result["cost_model"]["charged_months"])
        self.assertEqual([42.0, 42.0], [row["pnl"] for row in result["accepted"]])

    def test_production_growth_sizing_matches_live_tiers(self) -> None:
        result = simulate_policy(
            [candidate("A", "SPY", 0, return_pct=10)],
            policy="all_affordable", starting_capital=5_000,
            sizing_model="production_growth_v1",
        )
        self.assertEqual(7, result["accepted"][0]["quantity"])
        self.assertEqual("growth", result["accepted"][0]["sizing_detail"]["tier"])

        bootstrap = simulate_policy(
            [candidate("A", "SPY", 0, return_pct=10)],
            policy="all_affordable", starting_capital=2_000,
            sizing_model="production_growth_v1",
        )
        self.assertEqual(4, bootstrap["accepted"][0]["quantity"])
        self.assertEqual("bootstrap", bootstrap["accepted"][0]["sizing_detail"]["tier"])

    def test_launch_report_records_account_slots_and_live_sizing(self) -> None:
        report = build_report(
            rows(datetime(2026, 3, 1, 10, tzinfo=timezone.utc), 95, 2),
            validation_start=date(2026, 4, 1),
            holdout_start=date(2026, 5, 1),
        )
        self.assertEqual(3, report["cost_assumptions"]["maximum_concurrent_positions"])
        self.assertEqual(
            "production_growth_v1",
            report["full_history_growth_diagnostic"]["current_all"]["sizing_model"],
        )

    def test_every_period_must_clear_the_1_5_net_pf_gate(self) -> None:
        payload = (
            rows(datetime(2026, 3, 1, 10, tzinfo=timezone.utc), 35, 10)
            + rows(datetime(2026, 6, 1, 10, tzinfo=timezone.utc), 35, 10)
            + rows(datetime(2026, 7, 1, 10, tzinfo=timezone.utc), 35, -10)
        )
        report = build_report(
            payload, validation_start=date(2026, 6, 1),
            holdout_start=date(2026, 7, 1),
        )
        current = report["launch_gates"]["current_all"]
        self.assertTrue(current["periods"]["eligibility"]["pf_at_least_1_50"])
        self.assertTrue(current["periods"]["validation"]["pf_at_least_1_50"])
        self.assertFalse(current["periods"]["holdout"]["pf_at_least_1_50"])
        self.assertFalse(current["passed_all_periods"])
        self.assertFalse(report["decision"]["passed"])

    def test_report_applies_costs_and_does_not_claim_100k(self) -> None:
        payload = rows(datetime(2026, 3, 1, 10, tzinfo=timezone.utc), 95, 2)
        report = build_report(
            payload, validation_start=date(2026, 4, 1),
            holdout_start=date(2026, 5, 1),
        )
        summary = report["full_history_growth_diagnostic"]["current_all"]
        self.assertGreater(summary["cost_model"]["transaction_costs"], 0)
        self.assertGreater(summary["cost_model"]["subscription_costs"], 0)
        self.assertLess(summary["ending_cash"], report["target_capital"])
        self.assertIn("Do not represent", report["decision"]["reason"])

    def test_exhaustive_subset_selection_is_frozen_before_later_periods(self) -> None:
        primary = "V2_SPY_FAILED_RANGE_RECOVERY"
        alternative = "V2_ORB_PULLBACK"
        payload = (
            strategy_rows(primary, "SPY", datetime(2026, 1, 1, 10, tzinfo=timezone.utc), [30, 30, 30, -10, -10] * 7)
            + strategy_rows(alternative, "TSLA", datetime(2026, 1, 1, 11, tzinfo=timezone.utc), [10, 10, 10, 10, -10] * 7)
            + strategy_rows(primary, "SPY", datetime(2026, 3, 1, 10, tzinfo=timezone.utc), [-10] * 35)
            + strategy_rows(alternative, "TSLA", datetime(2026, 3, 1, 11, tzinfo=timezone.utc), [20, 20, 20, 20, -10] * 7)
            + strategy_rows(primary, "SPY", datetime(2026, 5, 1, 10, tzinfo=timezone.utc), [-10] * 35)
            + strategy_rows(alternative, "TSLA", datetime(2026, 5, 1, 11, tzinfo=timezone.utc), [20, 20, 20, 20, -10] * 7)
        )
        report = build_report(
            payload,
            validation_start=date(2026, 3, 1),
            holdout_start=date(2026, 5, 1),
        )
        screen = report["exhaustive_subset_screen"]
        self.assertEqual(63, screen["candidate_count"])
        self.assertEqual([primary], screen["selected"]["strategy_ids"])
        self.assertTrue(screen["selected"]["eligibility_passed"])
        self.assertFalse(screen["selected"]["gates"]["validation"]["net_profitable"])
        self.assertFalse(screen["passed_all_periods"])


if __name__ == "__main__":
    unittest.main()
