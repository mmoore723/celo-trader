#!/usr/bin/env python3
"""Rank a small, pre-declared ORB configuration grid without touching holdout bars.

This ranks underlying behaviour only. A candidate is never promoted from this
script: its untouched holdout dates still require real option bid/ask testing.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import time
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.simulator import SimulationConfig, Simulator
from research.engine.strategies import OpeningRangeBreakout, OpeningRangeBreakoutConfig
from research.engine.validation import ValidationConfig, validate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-trades", type=int, default=20,
                        help="Minimum in-sample trades before a setting can be a candidate (default: 20).")
    parser.add_argument("--top", type=int, default=10,
                        help="Number of settings to include in each report section (default: 10).")
    args = parser.parse_args()
    bars = load_csv(args.bars).bars
    split = int(len(bars) * .70)
    train, holdout = bars[:split], bars[split:]
    simulator = Simulator(SimulationConfig(session_exit_time=time(15, 55)))
    if args.min_trades < 1:
        parser.error("--min-trades must be at least 1")
    gate = ValidationConfig(min_trades=args.min_trades)
    results = []
    for minimum, maximum, buffer, deadline, stop, reward in product(
        # This is intentionally a small, declared search space.  It is broad
        # enough to test a quieter opening, but not broad enough to let us
        # keep retrying settings until a lucky one appears.
        (.0005, .001, .0015, .002, .0025), (.006, .008, .010, .012), (0, .0002, .0004),
        (time(10, 30), time(11)), (.4, .5, .6), (1.25, 1.5, 2.0),
    ):
        if minimum >= maximum:
            continue
        config = OpeningRangeBreakoutConfig(minimum, maximum, buffer, deadline, stop, reward)
        train_result = validate(simulator.run(train, OpeningRangeBreakout(config)), gate)
        results.append({"config": {"min_range_pct": minimum, "max_range_pct": maximum,
            "buffer_pct": buffer, "deadline": deadline.isoformat(), "stop_fraction": stop,
            "reward_risk": reward}, "train": train_result.__dict__})
    def rank(item: dict) -> tuple[float, float, float]:
        report = item["train"]
        # Do not let a high profit factor from a tiny sample outrank a
        # sufficiently large sample.  Every qualified setting is still only
        # a candidate for untouched option-quote testing, never a promotion.
        return (report["trade_count"], report["profit_factor"], report["net_pnl"])

    qualified = [item for item in results if item["train"]["passed"]]
    qualified.sort(key=rank, reverse=True)
    results.sort(key=rank, reverse=True)
    payload = {
        "purpose": "Train-only ORB screening; holdout bars and option quotes are untouched.",
        "decision_rule": (
            f"Only settings with at least {args.min_trades} modeled training trades, positive modeled P&L, "
            "profit factor >= 1.15, and drawdown <= 15% may proceed to quote validation."
        ),
        "bars": len(bars), "train_bars": len(train), "holdout_bars": len(holdout),
        "settings_tested": len(results), "qualified_candidate_count": len(qualified),
        "qualified_train_candidates": qualified[:args.top],
        "largest_samples_not_qualified": results[:args.top],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
