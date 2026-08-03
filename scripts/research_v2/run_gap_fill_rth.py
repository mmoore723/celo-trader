"""Run the RTH gap-fill candidate on frozen data only."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import GapFillRTH
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward


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
                              GapFillRTH, simulation, ValidationConfig())
    cfg = asdict(simulation.config)
    cfg["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({"research_only": True, "strategy": GapFillRTH.strategy_id,
                      "dataset_sha256": dataset.sha256,
                      "entry_source": "TradingView IU Gap Fill (RTH adaptation)",
                      "exit_policy": "2 ATR bar-close trailing stop; RTH session exit; no fixed profit target",
                      "simulation": cfg, "train": pack(report.train_validation),
                      "holdout": pack(report.holdout_validation), "promoted": report.promoted},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
