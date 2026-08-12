"""Run the RTH Turtle Soup candidate on frozen data only."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.simulator import SimulationConfig, Simulator
from research.engine.strategies import TurtleSoupRTH
from research.engine.validation import ValidationConfig
from research.engine.walk_forward import run_walk_forward


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
    report = run_walk_forward(dataset.bars, datetime.fromisoformat(args.split.replace("Z", "+00:00")),
                              TurtleSoupRTH, simulation, ValidationConfig())
    cfg = asdict(simulation.config)
    cfg["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({"research_only": True, "strategy": TurtleSoupRTH.strategy_id,
                      "dataset_sha256": dataset.sha256, "entry_source": "TradingView Turtle Soup 1-Bar Confirmation",
                      "exit_policy": "1.5R fixed target; stop at sweep extreme; RTH session exit",
                      "simulation": cfg, "train": pack(report.train_validation),
                      "holdout": pack(report.holdout_validation), "promoted": report.promoted},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
