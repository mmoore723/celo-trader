#!/usr/bin/env python3
"""Screen clean intraday strategy hypotheses before tuning or quote spending.

This is deliberately a *baseline* screen, not a parameter search.  It makes
the order of work clear: reject a weak idea on frozen underlying bars first;
only then consider a small train-only tuning grid and finally real option
bid/ask validation.  It has no broker access and cannot submit an order.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.simulator import SimulationConfig, Simulator
from research_v2.strategies import (
    AfternoonReversal, EMAPullbackRTH, FairValueGap, GapFillRTH,
    OpeningRangePullback, TurtleSoupRTH, VWAPReversionRTH,
)
from research_v2.validation import ValidationConfig
from research_v2.walk_forward import run_walk_forward


# Each is a separately implemented premise.  The screen does not reinstate a
# legacy strategy: any result must still pass both periods before tuning.
HYPOTHESES = (
    EMAPullbackRTH, TurtleSoupRTH, GapFillRTH, VWAPReversionRTH,
    FairValueGap, AfternoonReversal, OpeningRangePullback,
)


def _metrics(result) -> dict[str, object]:
    return {
        "passed": result.passed,
        "trades": result.trade_count,
        "net_pnl": result.net_pnl,
        "expectancy": result.expectancy,
        "profit_factor": result.profit_factor,
        "max_drawdown_pct": result.max_drawdown_pct,
        "reasons": list(result.reasons),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Frozen regular-session OHLCV CSV")
    parser.add_argument("--split", required=True, help="ISO time; later bars are untouched holdout")
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.min_trades < 1:
        parser.error("--min-trades must be at least 1")

    dataset = load_csv(args.csv)
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    simulator = Simulator(SimulationConfig(session_exit_time=time(15, 55)))
    gates = ValidationConfig(min_trades=args.min_trades)
    rows = []
    for factory in HYPOTHESES:
        report = run_walk_forward(dataset.bars, split, factory, simulator, gates)
        rows.append({
            "strategy": factory.strategy_id,
            "qualified_for_train_only_tuning": report.promoted,
            "train": _metrics(report.train_validation),
            "holdout": _metrics(report.holdout_validation),
        })
    payload = {
        "purpose": "Baseline screen only; no paid option quotes, tuning, or trading action.",
        "decision_rule": (
            "A strategy must pass both frozen periods before a limited train-only tuning run. "
            "No result here authorizes paper or live trading."
        ),
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256, "bars": len(dataset.bars)},
        "split": split.isoformat(), "gates": asdict(gates), "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
