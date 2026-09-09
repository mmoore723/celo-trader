"""Focused causality tests for the Two-Leg dynamic-exit experiment."""
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.engine.fixed_contract_exits import ExactContractEpisode, price_exact_contract_exits
from research.engine.models import Bar, Side, Signal
from research.engine.two_leg_dynamic_exits import planned_two_leg_dynamic_exits
from research.jobs.assess_tsla_two_leg_dynamic_exits import assess, comparable_rows


def _bar(minute: int, close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    stamp = datetime(2026, 1, 2, 9, 30, tzinfo=UTC) + timedelta(minutes=minute)
    high = max(close, close + .2) if high is None else high
    low = min(close, close - .2) if low is None else low
    return Bar(stamp, close, high, low, close, 100)


class TwoLegDynamicExitTests(unittest.TestCase):
    def test_trail_cannot_fire_on_the_candle_that_arms_it(self) -> None:
        bars = tuple(_bar(i, 100) for i in range(20))
        entry = bars[15]
        signal = Signal("two_leg", Side.LONG, bars[14].timestamp, 100, 99, 102)
        arm = _bar(16, 101.1, high=101.2, low=99.0)
        plans = planned_two_leg_dynamic_exits((*bars[:16], arm, *bars[17:]), signal, entry)
        self.assertEqual("time_cap_90m", plans["armed_chandelier_3atr_90m"].reason)

    def test_armed_long_trail_uses_next_completed_bar_and_one_minute_delay(self) -> None:
        bars = list(_bar(i, 100) for i in range(18))
        entry = bars[15]
        signal = Signal("two_leg", Side.LONG, bars[14].timestamp, 100, 99, 102)
        bars[16] = _bar(16, 101.1, high=101.2, low=100.8)
        bars[17] = _bar(17, 99.5, high=101.3, low=99.4)
        plan = planned_two_leg_dynamic_exits(bars, signal, entry)["armed_chandelier_3atr_90m"]
        self.assertEqual("armed_chandelier_3atr", plan.reason)
        self.assertEqual(bars[17].timestamp + timedelta(minutes=1), plan.time)

    def test_armed_short_trail_is_symmetric(self) -> None:
        bars = list(_bar(i, 100) for i in range(18))
        entry = bars[15]
        signal = Signal("two_leg", Side.SHORT, bars[14].timestamp, 100, 101, 98)
        bars[16] = _bar(16, 98.9, high=99.1, low=98.8)
        bars[17] = _bar(17, 100.5, high=100.6, low=98.7)
        plan = planned_two_leg_dynamic_exits(bars, signal, entry)["armed_chandelier_3atr_90m"]
        self.assertEqual("armed_chandelier_3atr", plan.reason)

    def test_dynamic_decision_never_extends_past_fixed_cap(self) -> None:
        bars = list(_bar(i, 100) for i in range(107))
        entry = bars[15]
        signal = Signal("two_leg", Side.LONG, bars[14].timestamp, 100, 99, 102)
        bars[104] = _bar(104, 101.1, high=101.2, low=100.8)
        bars[105] = _bar(105, 99.5, high=101.3, low=99.4)
        plan = planned_two_leg_dynamic_exits(bars, signal, entry)["armed_chandelier_3atr_90m"]
        self.assertEqual(entry.timestamp + timedelta(minutes=90), plan.time)
        self.assertEqual("time_cap_90m", plan.reason)

    def test_exact_contract_pricing_keeps_entry_and_uses_first_real_bid(self) -> None:
        start = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.csv"
            path.write_text(
                "timestamp,symbol,bid,ask\n"
                f"{start.isoformat()},OTHER,9,10\n"
                f"{(start + timedelta(minutes=1)).isoformat()},TSLA  260109C00100000,2.00,2.10\n"
                f"{(start + timedelta(minutes=1, seconds=10)).isoformat()},TSLA  260109C00100000,2.20,2.30\n",
                encoding="utf-8",
            )
            episode = ExactContractEpisode(start, start, "TSLA  260109C00100000", 1.90)
            from research.engine.exit_rules import PlannedExit
            result = price_exact_contract_exits(
                path, episode, {"fixed": PlannedExit("fixed", start + timedelta(minutes=1), "cap")},
            )["fixed"]
        self.assertEqual(1.90, result["entry_ask"])
        self.assertEqual(2.00, result["exit_bid"])
        self.assertEqual("TSLA  260109C00100000", result["contract"])
        self.assertEqual(0, result["exit_quote_delay_seconds"])

    def test_assessment_uses_common_rows_and_never_selects_from_holdout(self) -> None:
        def row(day: str, pnl: float) -> dict[str, object]:
            return {"signal_time": f"{day}T10:00:00+00:00",
                    "net_pnl_one_contract": pnl, "net_return_pct": pnl}
        rules = ("fixed_90m", "structural_stop_90m", "confirmed_vwap_ema_90m",
                 "armed_chandelier_3atr_90m", "hybrid_armed_chandelier_vwap_ema_90m")
        training_days = [f"2026-01-{day:02d}" for day in range(1, 11)]
        rows = {rule: [row(day, 1) for day in training_days] for rule in rules}
        rows["structural_stop_90m"] = [row(day, -1) for day in training_days]
        for rule in rules:
            rows[rule].append(row("2026-03-01", 1000 if rule == "structural_stop_90m" else 1))
        rows["structural_stop_90m"].append(row("2026-04-01", 5000))
        common = comparable_rows(rows)
        self.assertEqual(11, len(common["structural_stop_90m"]))
        result = assess(common, date(2026, 2, 1), minimum_training=10, minimum_holdout=1)
        self.assertNotEqual("structural_stop_90m", result["selected_on_training"])


if __name__ == "__main__":
    unittest.main()
