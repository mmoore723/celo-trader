"""Run the RTH EMA-pullback candidate on frozen data only."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv, resample_regular_session
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import EMAPullbackRTH
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
    # The TradingView source explicitly targets 15-minute charts.  The frozen
    # research artifact is 5-minute data, so aggregate it deterministically
    # instead of pretending the source's lookback lengths mean the same thing.
    bars = resample_regular_session(dataset.bars, source_minutes=5, target_minutes=15)
    simulation = Simulator(SimulationConfig(session_exit_time=time(15, 55)))
    report = run_walk_forward(bars, datetime.fromisoformat(args.split.replace("Z", "+00:00")),
                              EMAPullbackRTH, simulation, ValidationConfig())
    cfg = asdict(simulation.config)
    cfg["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({"research_only": True, "strategy": EMAPullbackRTH.strategy_id,
                      "dataset_sha256": dataset.sha256,
                      "bar_aggregation": {"source_minutes": 5, "strategy_minutes": 15,
                                          "input_bars": len(dataset.bars), "output_bars": len(bars)},
                      "simulation": cfg,
                      "train": pack(report.train_validation), "holdout": pack(report.holdout_validation),
                      "promoted": report.promoted}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
