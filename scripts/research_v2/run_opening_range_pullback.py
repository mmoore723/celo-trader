"""Run V2 Opening Range Pullback against one frozen OHLCV dataset.

Research-only: this command cannot contact a broker or place an order.
"""

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
from research_v2.strategies import OpeningRangePullback
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward


def _payload(result) -> dict:
    return {"passed": result.passed, "trade_count": result.trade_count, "net_pnl": result.net_pnl,
            "expectancy": result.expectancy, "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct, "reasons": list(result.reasons)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--split", required=True, help="ISO timestamp; later bars are untouched holdout")
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-trades", type=int, default=30)
    args = parser.parse_args()
    dataset = load_csv(args.csv)
    simulation = Simulator(SimulationConfig(
        risk_fraction=args.risk_pct / 100.0,
        slippage_bps=args.slippage_bps,
        session_exit_time=time(15, 55),
    ))
    gates = ValidationConfig(min_trades=args.min_trades)
    report = run_walk_forward(dataset.bars, datetime.fromisoformat(args.split.replace("Z", "+00:00")),
                              OpeningRangePullback, simulation, gates)
    simulation_payload = asdict(simulation.config)
    simulation_payload["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({
        "research_only": True, "strategy": OpeningRangePullback.strategy_id,
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256, "start": dataset.start.isoformat(),
                    "end": dataset.end.isoformat(), "bars": len(dataset.bars)},
        "split": args.split, "simulation": simulation_payload, "gates": asdict(gates),
        "train": _payload(report.train_validation), "holdout": _payload(report.holdout_validation),
        "promoted": report.promoted,
        "promotion_message": ("Eligible only for portfolio comparison; cannot place an order."
                              if report.promoted else "Not eligible for portfolio comparison or paper observation."),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
