"""Run the exact TradingView SuperTrend reversal candidate on frozen data only."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.strategies.supertrend_reversal import SuperTrendReversal, SuperTrendReversalConfig
from research_v2.supertrend_simulator import ReversalSimulationConfig, SuperTrendReversalSimulator
from research_v2.validation import ValidationConfig, validate


def _payload(trades, gates):
    result = validate(trades, gates)
    return {"passed": result.passed, "trade_count": result.trade_count, "net_pnl_one_unit": result.net_pnl,
            "expectancy_one_unit": result.expectancy, "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown_pct, "reasons": list(result.reasons)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-trades", type=int, default=30)
    args = parser.parse_args()
    dataset = load_csv(args.csv)
    split = datetime.fromisoformat(args.split.replace("Z", "+00:00"))
    train = tuple(bar for bar in dataset.bars if bar.timestamp < split)
    holdout = tuple(bar for bar in dataset.bars if bar.timestamp >= split)
    simulation = SuperTrendReversalSimulator(ReversalSimulationConfig(slippage_bps=args.slippage_bps))
    gates = ValidationConfig(min_trades=args.min_trades)
    config = SuperTrendReversalConfig()
    print(json.dumps({
        "research_only": True,
        "source": "https://www.tradingview.com/script/P5Gu6F8k/",
        "source_fidelity": "Pine v4 ATR/RMA SuperTrend flip; next-bar reversal fill; one underlying unit",
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256, "bars": len(dataset.bars)},
        "split": args.split, "strategy": asdict(config), "simulation": asdict(simulation.config),
        "train": _payload(simulation.run(train, SuperTrendReversal(config)), gates),
        "holdout": _payload(simulation.run(holdout, SuperTrendReversal(config)), gates),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
