"""Run the V2 Trend Continuation hypothesis against one fingerprinted CSV.

This is research-only. It reads OHLCV bars, never calls a broker, and cannot
submit an order.  It prints JSON so results can be saved beside the source
dataset and compared without narrative drift.

Example (requires a prepared historical CSV):
    python3 scripts/research.engine/run_trend_continuation.py \
      --csv research_data/SPY_5m.csv --split 2026-07-15T09:30:00-04:00
"""

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
from research.engine.strategies import TrendContinuation
from research.engine.validation import ValidationConfig
from research.engine.walk_forward import run_walk_forward


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
        # The production bot is intraday.  A research result must not borrow
        # overnight price movement that an intraday option position could not
        # capture.
        session_exit_time=time(15, 55),
    ))
    gates = ValidationConfig(min_trades=args.min_trades)
    report = run_walk_forward(dataset.bars, split, TrendContinuation, simulation, gates)
    simulation_payload = asdict(simulation.config)
    simulation_payload["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    output = {
        "research_only": True,
        "strategy": TrendContinuation.strategy_id,
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256,
                    "start": dataset.start.isoformat(), "end": dataset.end.isoformat(),
                    "bars": len(dataset.bars)},
        "split": split.isoformat(),
        "simulation": simulation_payload,
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
