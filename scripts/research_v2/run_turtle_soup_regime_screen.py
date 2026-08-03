"""Test whether Turtle Soup works only in train-selected, prior-measurable regimes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.regime import run_regime_walk_forward
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import TurtleSoupRTH
from research_v2.validation import ValidationConfig


def pack(result):
    return {"passed": result.passed, "trade_count": result.trade_count, "net_pnl": result.net_pnl,
            "expectancy": result.expectancy, "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct, "reasons": list(result.reasons)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--split", required=True)
    args = parser.parse_args()
    dataset = load_csv(args.csv)
    simulation = Simulator(SimulationConfig(session_exit_time=time(15, 55)))
    report = run_regime_walk_forward(dataset.bars, datetime.fromisoformat(args.split.replace("Z", "+00:00")),
                                     TurtleSoupRTH, simulation, ValidationConfig())
    cfg = asdict(simulation.config)
    cfg["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({"research_only": True, "strategy": TurtleSoupRTH.strategy_id,
                      "dataset_sha256": dataset.sha256, "dynamic_rule": "select prior 20-bar regime+side only from train",
                      "selected_train_keys": report.selected_keys, "simulation": cfg,
                      "train_all": pack(report.train_all), "train_selected": pack(report.train_selected),
                      "holdout_all": pack(report.holdout_all), "holdout_selected": pack(report.holdout_selected),
                      "promoted": report.promoted}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
