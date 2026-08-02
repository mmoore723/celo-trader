"""Run the independent V2 VWAP Pullback hypothesis against frozen OHLCV.

This research command cannot contact a broker or submit an order. It uses
next-bar fills and the same train/holdout gates as every V2 hypothesis.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import VWAPPullback
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward


def _result_payload(result) -> dict:
    return {
        "passed": result.passed,
        "trade_count": result.trade_count,
        "net_pnl": result.net_pnl,
        "expectancy": result.expectancy,
        "profit_factor": result.profit_factor,
        "max_drawdown_pct": result.max_drawdown_pct,
        "reasons": list(result.reasons),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Chronological OHLCV CSV")
    parser.add_argument("--split", required=True, help="ISO timestamp; later bars are untouched holdout")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="Research risk %% per trade (default 1)")
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-trades", type=int, default=30)
    args = parser.parse_args()

    dataset = load_csv(args.csv)
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    simulation = Simulator(SimulationConfig(
        risk_fraction=args.risk_pct / 100.0, slippage_bps=args.slippage_bps,
    ))
    gates = ValidationConfig(min_trades=args.min_trades)
    report = run_walk_forward(dataset.bars, split, VWAPPullback, simulation, gates)
    output = {
        "research_only": True,
        "strategy": VWAPPullback.strategy_id,
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256,
                    "start": dataset.start.isoformat(), "end": dataset.end.isoformat(),
                    "bars": len(dataset.bars)},
        "split": split.isoformat(),
        "simulation": asdict(simulation.config),
        "gates": asdict(gates),
        "train": _result_payload(report.train_validation),
        "holdout": _result_payload(report.holdout_validation),
        "promoted": report.promoted,
        "promotion_message": (
            "Eligible only for portfolio comparison; cannot place an order."
            if report.promoted else
            "Not eligible for portfolio comparison or paper observation."
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
