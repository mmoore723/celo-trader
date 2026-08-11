"""Run the V2 later-morning base breakdown hypothesis on frozen OHLCV bars.

The output is an underlying-price screening result only.  It cannot prove an
options strategy; a candidate must subsequently pass ask-to-bid option quote
testing from the already-paid TSLA archive.
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
from research_v2.strategies import MiddayBreakdown
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward


def _payload(result) -> dict:
    return {"passed": result.passed, "trade_count": result.trade_count, "net_pnl": result.net_pnl,
            "expectancy": result.expectancy, "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct, "reasons": list(result.reasons)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--split", required=True, help="ISO timestamp; later bars stay untouched")
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-trades", type=int, default=30)
    args = parser.parse_args()
    dataset = load_csv(args.csv)
    simulation = Simulator(SimulationConfig(
        risk_fraction=args.risk_pct / 100.0, slippage_bps=args.slippage_bps,
        session_exit_time=time(15, 55),
    ))
    report = run_walk_forward(
        dataset.bars, datetime.fromisoformat(args.split.replace("Z", "+00:00")),
        MiddayBreakdown, simulation, ValidationConfig(min_trades=args.min_trades),
    )
    simulation_payload = asdict(simulation.config)
    simulation_payload["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({
        "research_only": True, "strategy": MiddayBreakdown.strategy_id,
        "hypothesis": "10:00-11:00 compact base, then first confirmed close below its low and VWAP",
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256,
                    "start": dataset.start.isoformat(), "end": dataset.end.isoformat(), "bars": len(dataset.bars)},
        "split": args.split, "simulation": simulation_payload,
        "train": _payload(report.train_validation), "holdout": _payload(report.holdout_validation),
        "promoted": report.promoted,
        "promotion_message": ("Only eligible for paid option-quote testing." if report.promoted
                              else "Rejected before option-quote testing."),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
