"""Run the exact TradingView SuperTrend reversal candidate on frozen data only."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.strategies.supertrend_reversal import SuperTrendReversal, SuperTrendReversalConfig
from research.engine.supertrend_simulator import ReversalSimulationConfig, SuperTrendReversalSimulator
from research.engine.validation import ValidationConfig, validate


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
    simulation_payload = asdict(simulation.config)
    if simulation.config.session_exit_time is not None:
        simulation_payload["session_exit_time"] = simulation.config.session_exit_time.isoformat()
    print(json.dumps({
        "research_only": True,
        "source": "https://www.tradingview.com/script/P5Gu6F8k/",
        "source_fidelity": "Pine v4 ATR/RMA SuperTrend flip; next-bar reversal fill; intraday RTH close; one underlying unit",
        "dataset": {"path": dataset.source_path, "sha256": dataset.sha256, "bars": len(dataset.bars)},
        "split": args.split, "strategy": asdict(config), "simulation": simulation_payload,
        "train": _payload(simulation.run(train, SuperTrendReversal(config)), gates),
        "holdout": _payload(simulation.run(holdout, SuperTrendReversal(config)), gates),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
