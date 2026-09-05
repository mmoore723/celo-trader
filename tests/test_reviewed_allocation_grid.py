from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import unittest

from research.jobs.evaluate_reviewed_allocation_grid import (
    PROVEN,
    allocation_map,
    apply_current_portfolio_policy,
    build_report,
)


STRATEGIES = (
    "V2_SPY_FAILED_RANGE_RECOVERY",
    "V2_SPY_TREND_CONT",
    "V2_SPY_AFTERNOON_FVG",
    "V2_ORB_PULLBACK",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG",
)


def _rows(start: datetime, count: int, return_pct: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        strategy_id = STRATEGIES[index % len(STRATEGIES)]
        signal = start + timedelta(days=index, hours=index % 6)
        entry = signal + timedelta(minutes=1)
        rows.append({
            "strategy_id": strategy_id,
            "ticker": "SPY" if strategy_id.startswith("V2_SPY") else "TSLA",
            "evidence_grade": "passed_declared_holdout" if strategy_id in PROVEN else "promising_inconsistent",
            "signal_time": signal.isoformat(),
            "entry_time": entry.isoformat(),
            "exit_time": (entry + timedelta(minutes=30)).isoformat(),
            "entry_ask": 1.0,
            "exit_bid": 1.0 + return_pct / 100,
            "return_pct": return_pct,
        })
    return rows


class ReviewedAllocationGridTests(unittest.TestCase):
    def test_current_policy_only_removes_spy_trend_in_reserved_window(self) -> None:
        # 18:00 UTC is 14:00 EDT and must be reserved. The signal fixture adds
        # one minute before entry, so start it at 17:59 UTC.
        rows = _rows(datetime(2026, 6, 1, 17, 59, tzinfo=timezone.utc), 1, 5)
        rows[0]["strategy_id"] = "V2_SPY_TREND_CONT"
        rows[0]["ticker"] = "SPY"
        self.assertEqual(apply_current_portfolio_policy(rows), [])
        rows[0]["strategy_id"] = "V2_SPY_AFTERNOON_FVG"
        self.assertEqual(len(apply_current_portfolio_policy(rows)), 1)

    def test_current_policy_does_not_mistake_utc_morning_for_et_afternoon(self) -> None:
        # 14:00 UTC is 10:00 EDT, outside the reserved afternoon window.
        rows = _rows(datetime(2026, 6, 1, 13, 59, tzinfo=timezone.utc), 1, 5)
        rows[0]["strategy_id"] = "V2_SPY_TREND_CONT"
        rows[0]["ticker"] = "SPY"
        self.assertEqual(len(apply_current_portfolio_policy(rows)), 1)

    def test_current_policy_converts_standard_time_too(self) -> None:
        # 19:00 UTC is 14:00 EST in January.
        rows = _rows(datetime(2026, 1, 5, 18, 59, tzinfo=timezone.utc), 1, 5)
        rows[0]["strategy_id"] = "V2_SPY_TREND_CONT"
        rows[0]["ticker"] = "SPY"
        self.assertEqual(apply_current_portfolio_policy(rows), [])

    def test_holdout_returns_cannot_change_selected_allocations(self) -> None:
        eligibility = _rows(datetime(2026, 3, 1, 10, tzinfo=timezone.utc), 50, 5)
        validation = _rows(datetime(2026, 6, 1, 10, tzinfo=timezone.utc), 25, 5)
        positive_holdout = _rows(datetime(2026, 7, 1, 10, tzinfo=timezone.utc), 50, 10)
        negative_holdout = _rows(datetime(2026, 7, 1, 10, tzinfo=timezone.utc), 50, -10)
        positive = build_report(
            eligibility + validation + positive_holdout,
            validation_start=date(2026, 6, 1), holdout_start=date(2026, 7, 1),
        )
        negative = build_report(
            eligibility + validation + negative_holdout,
            validation_start=date(2026, 6, 1), holdout_start=date(2026, 7, 1),
        )
        self.assertEqual(
            positive["selected_before_holdout"]["group_allocations"],
            negative["selected_before_holdout"]["group_allocations"],
        )

    def test_allocation_map_covers_every_reviewed_strategy(self) -> None:
        self.assertEqual(set(allocation_map(.2, .1, .05)), set(STRATEGIES))


if __name__ == "__main__":
    unittest.main()
