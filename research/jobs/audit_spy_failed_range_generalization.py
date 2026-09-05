#!/usr/bin/env python3
"""Reproduce and stress-test SPY Failed-Range Recovery on long history.

This is an underlying-direction diagnostic, not an option backtest.  It uses
the exact production signal detector, enters on the next one-minute open,
exits on a later completed one-minute close, and subtracts a declared
round-trip return allowance.  Every calendar period is reported separately so
a rule cannot hide one losing year inside a profitable aggregate.

The confirmation variants are retrospective diagnostics.  They never change
a saved strategy switch and cannot promote a strategy to order authority.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
import json
from pathlib import Path
import statistics
import sys
from typing import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.models import Bar as ResearchBar
from strategies.market_structure import Bar, Side
from strategies.spy_failed_range_recovery_v2 import (
    BREAKOUT_DEADLINE,
    MINIMUM_EXCURSION_RANGE,
    _candidate_from_completed_bars,
)


REFERENCE_DATA_SHA256 = "07c7ef29ef6a776964ee7fc841487d71971a1316b2744d767eb8e3a8919a7f40"
REFERENCE_BASELINE = {
    "2024": {"trades": 139, "wins": 78, "net_return_pct": 1.6553, "profit_factor": 1.1825},
    "2025": {"trades": 160, "wins": 71, "net_return_pct": -1.8297, "profit_factor": 0.8848},
    "2026": {"trades": 84, "wins": 42, "net_return_pct": 0.7006, "profit_factor": 1.0820},
}
DEFAULT_HOLDS = (5, 10, 15, 20, 30, 45, 60, 90)
CONFIRMATION_VARIANTS = {
    "baseline": "Enter on the first minute after the completed reclaim candle.",
    "next_bar_follow_through": "Require the next close to move farther in the reversal direction; enter one minute later.",
    "next_bar_breaks_trigger": "Require the next close to break the reclaim candle high/low; enter one minute later.",
    "two_bar_follow_through": "Require two consecutive closes in the reversal direction; enter one minute later.",
    "quarter_range_progress": "Wait up to 30 minutes for a close one-quarter inside the opening range; enter next minute.",
    "midpoint_progress": "Wait up to 30 minutes for a close beyond the opening-range midpoint; enter next minute.",
    "ema8_follow_through": "Wait up to 15 minutes for progress beyond the reclaim close and alignment with EMA8; enter next minute.",
    "three_bar_structure": "Wait up to 15 minutes for three higher lows/lower highs plus a structure break; enter next minute.",
    "boundary_retest": "Wait up to 10 minutes for an opening-range boundary retest and directional rejection; enter next minute.",
}


@dataclass(frozen=True)
class SessionCandidate:
    day: date
    side: Side
    bars: tuple[Bar, ...]
    breakout_index: int
    trigger_index: int
    range_high: float
    range_low: float
    vwap: float

    @property
    def width(self) -> float:
        return self.range_high - self.range_low


def _profit_factor(values: Iterable[float]) -> float | None:
    rows = list(values)
    gains = sum(value for value in rows if value > 0)
    losses = -sum(value for value in rows if value < 0)
    if losses:
        return gains / losses
    return None if not gains else float("inf")


def summarize(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    values = [float(row["net_return_pct"]) for row in rows]
    factor = _profit_factor(values)
    return {
        "trades": len(values),
        "wins": sum(value > 0 for value in values),
        "win_rate_pct": round(100 * sum(value > 0 for value in values) / len(values), 2)
        if values else None,
        "net_return_pct": round(sum(values), 4),
        "average_return_pct": round(statistics.mean(values), 4) if values else None,
        "median_return_pct": round(statistics.median(values), 4) if values else None,
        "profit_factor": round(factor, 4) if factor not in (None, float("inf")) else (
            "inf" if factor == float("inf") else None
        ),
    }


def _by_period(rows: Sequence[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        year: summarize([row for row in rows if str(row["day"]).startswith(year)])
        for year in ("2024", "2025", "2026")
    }


def _production_bars(rows: Sequence[ResearchBar]) -> tuple[Bar, ...]:
    return tuple(Bar(
        item.timestamp, item.open, item.high, item.low, item.close, item.volume,
    ) for item in rows if time(9, 30) <= item.timestamp.time() < time(16, 0))


def _candidate_for_session(day: date, bars: tuple[Bar, ...]) -> SessionCandidate | None:
    result = _candidate_from_completed_bars(bars)
    if result is None:
        return None
    side, trigger, _stop, vwap, range_high, range_low = result
    trigger_index = next(
        index for index, bar in enumerate(bars) if bar.timestamp == trigger.timestamp
    )
    width = range_high - range_low
    excursion = width * MINIMUM_EXCURSION_RANGE
    breakout_index = next(
        index for index, bar in enumerate(bars)
        if time(9, 45) <= bar.timestamp.time() <= BREAKOUT_DEADLINE
        and (bar.close >= range_high + excursion or bar.close <= range_low - excursion)
    )
    return SessionCandidate(
        day=day, side=side, bars=bars, breakout_index=breakout_index,
        trigger_index=trigger_index, range_high=range_high,
        range_low=range_low, vwap=vwap,
    )


def build_candidates(bars: Sequence[ResearchBar]) -> list[SessionCandidate]:
    by_day: dict[date, list[ResearchBar]] = defaultdict(list)
    for bar in bars:
        if time(9, 30) <= bar.timestamp.time() < time(16, 0):
            by_day[bar.timestamp.date()].append(bar)
    candidates = []
    for day in sorted(by_day):
        candidate = _candidate_for_session(day, _production_bars(by_day[day]))
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _ema(values: Sequence[float], length: int) -> float:
    value = float(values[0])
    alpha = 2.0 / (length + 1.0)
    for item in values[1:]:
        value = alpha * float(item) + (1.0 - alpha) * value
    return value


def confirmation_entry_index(candidate: SessionCandidate, variant: str) -> int | None:
    bars = candidate.bars
    trigger_index = candidate.trigger_index
    trigger = bars[trigger_index]
    sign = 1 if candidate.side is Side.LONG else -1
    if variant == "baseline":
        return trigger_index + 1
    if variant in {"next_bar_follow_through", "next_bar_breaks_trigger"}:
        check = trigger_index + 1
        if check >= len(bars):
            return None
        reference = trigger.close
        if variant == "next_bar_breaks_trigger":
            reference = trigger.high if sign > 0 else trigger.low
        return check + 1 if sign * (bars[check].close - reference) > 0 else None
    if variant == "two_bar_follow_through":
        first, second = trigger_index + 1, trigger_index + 2
        if second >= len(bars):
            return None
        passed = (
            sign * (bars[first].close - trigger.close) > 0
            and sign * (bars[second].close - bars[first].close) > 0
        )
        return second + 1 if passed else None
    if variant in {"quarter_range_progress", "midpoint_progress"}:
        fraction = 0.25 if variant == "quarter_range_progress" else 0.50
        level = (
            candidate.range_low + fraction * candidate.width
            if sign > 0 else candidate.range_high - fraction * candidate.width
        )
        for index in range(trigger_index + 1, min(trigger_index + 31, len(bars))):
            if sign * (bars[index].close - level) >= 0:
                return index + 1
        return None
    if variant == "ema8_follow_through":
        for index in range(trigger_index + 1, min(trigger_index + 16, len(bars))):
            closes = [bar.close for bar in bars[max(0, index - 19): index + 1]]
            ema8 = _ema(closes, 8)
            if (
                sign * (bars[index].close - trigger.close) > 0
                and sign * (bars[index].close - ema8) > 0
            ):
                return index + 1
        return None
    if variant == "three_bar_structure":
        for index in range(trigger_index + 3, min(trigger_index + 16, len(bars))):
            first, second, third = bars[index - 2:index + 1]
            passed = (
                first.low < second.low < third.low and third.close > first.high
                if sign > 0 else
                first.high > second.high > third.high and third.close < first.low
            )
            if passed:
                return index + 1
        return None
    if variant == "boundary_retest":
        boundary = candidate.range_low if sign > 0 else candidate.range_high
        for index in range(trigger_index + 1, min(trigger_index + 11, len(bars))):
            bar = bars[index]
            passed = (
                bar.low <= boundary + 0.05 * candidate.width
                and bar.close >= boundary + 0.10 * candidate.width
                and bar.close > bar.open
                if sign > 0 else
                bar.high >= boundary - 0.05 * candidate.width
                and bar.close <= boundary - 0.10 * candidate.width
                and bar.close < bar.open
            )
            if passed:
                return index + 1
        return None
    raise ValueError(f"unknown confirmation variant: {variant}")


def outcome(
    candidate: SessionCandidate, entry_index: int | None, *, hold_minutes: int,
    round_trip_cost_pct: float,
) -> dict[str, object] | None:
    if entry_index is None or entry_index >= len(candidate.bars):
        return None
    exit_index = entry_index + hold_minutes
    if exit_index >= len(candidate.bars):
        return None
    entry = candidate.bars[entry_index]
    exit_bar = candidate.bars[exit_index]
    sign = 1 if candidate.side is Side.LONG else -1
    net_return = sign * (exit_bar.close - entry.open) / entry.open * 100 - round_trip_cost_pct
    trigger = candidate.bars[candidate.trigger_index]
    breakout = candidate.bars[candidate.breakout_index]
    return {
        "day": candidate.day.isoformat(),
        "direction": candidate.side.value,
        "breakout_time": breakout.timestamp.isoformat(),
        "trigger_time": trigger.timestamp.isoformat(),
        "entry_time": entry.timestamp.isoformat(),
        "exit_time": exit_bar.timestamp.isoformat(),
        "entry_price": round(entry.open, 6),
        "exit_price": round(exit_bar.close, 6),
        "net_return_pct": round(net_return, 6),
    }


def _all_periods_pass(periods: dict[str, dict[str, object]], target: float) -> bool:
    return all(
        float(summary.get("profit_factor") or 0) >= target
        and float(summary.get("median_return_pct") or 0) > 0
        for summary in periods.values()
    )


def _matches_reference(periods: dict[str, dict[str, object]]) -> bool:
    for year, expected in REFERENCE_BASELINE.items():
        actual = periods[year]
        if actual["trades"] != expected["trades"] or actual["wins"] != expected["wins"]:
            return False
        for key in ("net_return_pct", "profit_factor"):
            if abs(float(actual[key]) - float(expected[key])) > 0.0001:
                return False
    return True


def audit(
    bars: Sequence[ResearchBar], *, source_path: str, source_sha256: str,
    round_trip_cost_pct: float = 0.02, target_profit_factor: float = 1.50,
) -> dict[str, object]:
    if round_trip_cost_pct < 0 or target_profit_factor <= 0:
        raise ValueError("cost must be non-negative and PF target must be positive")
    candidates = build_candidates(bars)
    fixed_holds: dict[str, object] = {}
    for hold in DEFAULT_HOLDS:
        rows = [
            row for candidate in candidates
            if (row := outcome(
                candidate, confirmation_entry_index(candidate, "baseline"),
                hold_minutes=hold, round_trip_cost_pct=round_trip_cost_pct,
            )) is not None
        ]
        periods = _by_period(rows)
        fixed_holds[str(hold)] = {
            "by_period": periods,
            "all_periods_pass": _all_periods_pass(periods, target_profit_factor),
        }
    confirmations: dict[str, object] = {}
    for variant, definition in CONFIRMATION_VARIANTS.items():
        rows = [
            row for candidate in candidates
            if (row := outcome(
                candidate, confirmation_entry_index(candidate, variant),
                hold_minutes=30, round_trip_cost_pct=round_trip_cost_pct,
            )) is not None
        ]
        periods = _by_period(rows)
        confirmations[variant] = {
            "definition": definition,
            "all": summarize(rows),
            "by_period": periods,
            "all_periods_pass": _all_periods_pass(periods, target_profit_factor),
            "accepted_days": [str(row["day"]) for row in rows],
        }
    baseline_periods = confirmations["baseline"]["by_period"]
    reference_match = _matches_reference(baseline_periods)
    return {
        "purpose": "Long-history generalization and causal confirmation audit for SPY Failed-Range Recovery.",
        "evidence_class": "underlying_directional_screen_not_option_profit_backtest",
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source_rows": len(bars),
        "periods": ["2024", "2025", "2026-01-01_through_2026-07-31"],
        "entry_model": "Exact production signal; next one-minute open unless the named confirmation delays entry.",
        "exit_model": "Completed one-minute close after the declared number of full minutes.",
        "round_trip_cost_pct": round_trip_cost_pct,
        "target_profit_factor": target_profit_factor,
        "candidate_sessions": len(candidates),
        "reference_data_hash_match": source_sha256 == REFERENCE_DATA_SHA256,
        "reference_baseline_match": reference_match,
        "baseline_reference": REFERENCE_BASELINE,
        "fixed_holds": fixed_holds,
        "confirmation_variants": confirmations,
        "passing_confirmation_variants": [
            name for name, result in confirmations.items() if result["all_periods_pass"]
        ],
        "passing_fixed_holds": [
            hold for hold, result in fixed_holds.items() if result["all_periods_pass"]
        ],
        "decision": (
            "No tested confirmation or fixed exit maintains PF 1.5 with a positive median in every calendar period. "
            "Do not present the current Failed-Range family as passed; keep collecting, and test a distinct entry "
            "family without changing the user's strategy switch."
        ),
        "complete": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--round-trip-cost-pct", type=float, default=0.02)
    parser.add_argument("--target-profit-factor", type=float, default=1.50)
    args = parser.parse_args()
    dataset = load_csv(args.bars)
    result = audit(
        dataset.bars, source_path=str(args.bars), source_sha256=dataset.sha256,
        round_trip_cost_pct=args.round_trip_cost_pct,
        target_profit_factor=args.target_profit_factor,
    )
    if result["reference_data_hash_match"] and not result["reference_baseline_match"]:
        raise SystemExit("frozen reference data no longer reproduces the reviewed baseline")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_sessions": result["candidate_sessions"],
        "reference_baseline_match": result["reference_baseline_match"],
        "passing_confirmation_variants": result["passing_confirmation_variants"],
        "passing_fixed_holds": result["passing_fixed_holds"],
        "decision": result["decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
