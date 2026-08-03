#!/usr/bin/env python3
"""Compare the TradingView-style EMA pullback on 5m and 15m bars.

The original public idea was built for 15-minute charts.  This study makes the
timeframe explicit instead of silently judging a port on a different chart.
Both variants use the same frozen source data, intraday session close, costs,
and untouched holdout.  It is research-only and cannot submit an order.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv, resample_regular_session
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import EMAPullbackRTH
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward


def _metrics(result) -> dict[str, object]:
    return {
        "passed": result.passed, "trades": result.trade_count, "net_pnl": result.net_pnl,
        "expectancy": result.expectancy, "profit_factor": result.profit_factor,
        "max_drawdown_pct": result.max_drawdown_pct, "reasons": list(result.reasons),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--split", required=True)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.min_trades < 1:
        parser.error("--min-trades must be at least 1")

    dataset = load_csv(args.csv)
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    simulator = Simulator(SimulationConfig(session_exit_time=time(15, 55)))
    gates = ValidationConfig(min_trades=args.min_trades)
    variants = []
    for minutes in (5, 15):
        bars = resample_regular_session(dataset.bars, source_minutes=5, target_minutes=minutes)
        report = run_walk_forward(bars, split, EMAPullbackRTH, simulator, gates)
        variants.append({
            "timeframe_minutes": minutes, "bars": len(bars),
            "qualified_for_train_only_tuning": report.promoted,
            "train": _metrics(report.train_validation), "holdout": _metrics(report.holdout_validation),
        })
    payload = {
        "purpose": "Frozen-data EMA timeframe study; no tuning, quotes, or trading action.",
        "decision_rule": "Only a variant passing both periods may receive limited train-only tuning.",
        "source": {"path": dataset.source_path, "sha256": dataset.sha256, "source_minutes": 5},
        "split": split.isoformat(), "gates": asdict(gates), "variants": variants,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
