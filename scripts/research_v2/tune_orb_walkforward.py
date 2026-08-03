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

from research_v2.data import load_csv
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import OpeningRangeBreakout, OpeningRangeBreakoutConfig
from research_v2.validation import ValidationConfig, validate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    bars = load_csv(args.bars).bars
    split = int(len(bars) * .70)
    train, holdout = bars[:split], bars[split:]
    simulator = Simulator(SimulationConfig(session_exit_time=time(15, 55)))
    gate = ValidationConfig(min_trades=12)
    results = []
    for minimum, maximum, buffer, deadline, stop, reward in product(
        (.0015, .002, .0025), (.008, .010, .012), (0, .0002, .0004),
        (time(10, 30), time(11)), (.4, .5, .6), (1.25, 1.5, 2.0),
    ):
        if minimum >= maximum:
            continue
        config = OpeningRangeBreakoutConfig(minimum, maximum, buffer, deadline, stop, reward)
        train_result = validate(simulator.run(train, OpeningRangeBreakout(config)), gate)
        results.append({"config": {"min_range_pct": minimum, "max_range_pct": maximum,
            "buffer_pct": buffer, "deadline": deadline.isoformat(), "stop_fraction": stop,
            "reward_risk": reward}, "train": train_result.__dict__})
    results.sort(key=lambda item: (item["train"]["passed"], item["train"]["profit_factor"], item["train"]["net_pnl"]), reverse=True)
    payload = {"purpose": "Train-only ORB ranking; holdout quotes are untouched.", "bars": len(bars),
               "train_bars": len(train), "holdout_bars": len(holdout), "top_train_candidates": results[:10]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))

if __name__ == "__main__":
    main()
