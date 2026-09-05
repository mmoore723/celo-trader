#!/usr/bin/env python3
"""Reproduce the TSLA Two-Leg directional-confirmation repair.

The job reads the frozen paid-option tuning report and frozen TSLA one-minute
bars.  Each saved option outcome is replayed through the exact production
state machine at its recorded signal minute.  It then calculates one-contract
ask-to-bid P&L after the current commission and adverse-slippage model.

This audit changes no strategy setting and places no order.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Iterable, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from trading.two_leg_trend_pullback_execution import _Bar, _signal_at_latest_bar


REFERENCE_BARS_SHA256 = "eeae427d707adc321538eb6f102cf513644723936e9d1f88d5549eca10e604ac"
REFERENCE_RESULTS = {
    "all": {"trades": 76, "wins": 43, "profit_factor": 2.0428},
    "older": {"trades": 66, "wins": 36, "profit_factor": 1.8237},
    "later": {"trades": 10, "wins": 7, "profit_factor": 3.9494},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _profit_factor(values: Iterable[float]) -> float | None:
    rows = list(values)
    gains = sum(value for value in rows if value > 0)
    losses = -sum(value for value in rows if value < 0)
    if losses:
        return gains / losses
    return None if not gains else float("inf")


def summarize(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    pnl = [float(row["net_pnl_one_contract"]) for row in rows]
    returns = [float(row["net_return_pct"]) for row in rows]
    factor = _profit_factor(pnl)
    return {
        "trades": len(rows),
        "wins": sum(value > 0 for value in pnl),
        "win_rate_pct": round(100 * sum(value > 0 for value in pnl) / len(pnl), 2) if pnl else None,
        "net_pnl_one_contract": round(sum(pnl), 2),
        "average_net_return_pct": round(statistics.mean(returns), 4) if returns else None,
        "median_net_return_pct": round(statistics.median(returns), 4) if returns else None,
        "profit_factor": round(factor, 4) if factor not in (None, float("inf")) else (
            "inf" if factor == float("inf") else None
        ),
    }


def _partition(rows: Sequence[dict[str, object]], cutoff: date, older: bool) -> list[dict[str, object]]:
    return [
        row for row in rows
        if (datetime.fromisoformat(str(row["signal_time"])).date() < cutoff) == older
    ]


def _production_bars(source_bars: Sequence[object]) -> dict[date, tuple[_Bar, ...]]:
    by_day: dict[date, list[_Bar]] = defaultdict(list)
    for bar in source_bars:
        if not (time(9, 30) <= bar.timestamp.time() <= time(15, 59)):
            continue
        by_day[bar.timestamp.date()].append(_Bar(
            timestamp=pd.Timestamp(bar.timestamp), open=float(bar.open), high=float(bar.high),
            low=float(bar.low), close=float(bar.close), volume=float(bar.volume), rvol=0.0,
        ))
    return {day: tuple(values) for day, values in by_day.items()}


def audit(
    tuning_report: dict[str, object], source_bars: Sequence[object], *,
    bars_path: str, bars_sha256: str, fee_per_contract_per_side: float = 0.65,
    slippage_price_per_side: float = 0.01,
) -> dict[str, object]:
    if fee_per_contract_per_side < 0 or slippage_price_per_side < 0:
        raise ValueError("execution costs cannot be negative")
    cutoff = date.fromisoformat(str(tuning_report["holdout_start"]))
    rows = tuning_report["markouts_by_variant_hold"]["baseline"]["90"]
    bars_by_day = _production_bars(source_bars)
    accepted: list[dict[str, object]] = []
    rejected = 0
    mismatches: list[dict[str, object]] = []
    for row in rows:
        signal_time = datetime.fromisoformat(str(row["signal_time"]))
        visible = tuple(
            bar for bar in bars_by_day.get(signal_time.date(), ())
            if bar.timestamp <= pd.Timestamp(signal_time)
        )
        signal = _signal_at_latest_bar(visible)
        if signal is None:
            rejected += 1
            continue
        expected_direction = "bullish" if row["side"] == "long" else "bearish"
        if signal.trigger_bar != pd.Timestamp(signal_time) or signal.direction != expected_direction:
            mismatches.append({
                "expected_time": str(row["signal_time"]), "expected_direction": expected_direction,
                "actual_time": signal.trigger_bar.isoformat(), "actual_direction": signal.direction,
            })
            continue
        entry_ask = float(row["entry_ask"])
        exit_bid = float(row["exit_bid"])
        entry_cost = entry_ask * 100 + fee_per_contract_per_side + slippage_price_per_side * 100
        exit_proceeds = exit_bid * 100 - fee_per_contract_per_side - slippage_price_per_side * 100
        net_pnl = exit_proceeds - entry_cost
        accepted.append({
            **row,
            "net_pnl_one_contract": round(net_pnl, 6),
            "net_return_pct": round(100 * net_pnl / entry_cost, 6),
        })
    if mismatches:
        raise RuntimeError(f"production replay mismatched {len(mismatches)} saved rows")
    summaries = {
        "all": summarize(accepted),
        "older": summarize(_partition(accepted, cutoff, True)),
        "later": summarize(_partition(accepted, cutoff, False)),
    }
    reference_matched = bars_sha256 == REFERENCE_BARS_SHA256
    for period, expected in REFERENCE_RESULTS.items():
        actual = summaries[period]
        reference_matched = reference_matched and actual["trades"] == expected["trades"]
        reference_matched = reference_matched and actual["wins"] == expected["wins"]
        reference_matched = reference_matched and abs(
            float(actual["profit_factor"]) - expected["profit_factor"]
        ) <= 0.0001
    return {
        "strategy": "V2_TSLA_TWO_LEG_TREND_PULLBACK",
        "repair": "completed reclaim candle has same-direction momentum, engulfing, or rejection",
        "bars_path": bars_path,
        "bars_sha256": bars_sha256,
        "hold_minutes": 90,
        "holdout_start": cutoff.isoformat(),
        "costs": {
            "fee_per_contract_per_side": fee_per_contract_per_side,
            "slippage_price_per_side": slippage_price_per_side,
        },
        "source_outcomes": len(rows),
        "accepted_outcomes": len(accepted),
        "rejected_outcomes": rejected,
        "summaries": summaries,
        "reference_matched": reference_matched,
        "decision": (
            "prospective_paper_repair; historical and later evidence support it, but fresh forward proof remains required"
            if reference_matched else "do_not_use; frozen reference did not reproduce"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="paid TSLA Two-Leg tuning JSON")
    parser.add_argument("--bars", type=Path, required=True, help="frozen TSLA one-minute CSV")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fee-per-contract-per-side", type=float, default=0.65)
    parser.add_argument("--slippage-price-per-side", type=float, default=0.01)
    args = parser.parse_args()
    result = audit(
        json.loads(args.input.read_text()), load_csv(args.bars).bars,
        bars_path=str(args.bars), bars_sha256=_sha256(args.bars),
        fee_per_contract_per_side=args.fee_per_contract_per_side,
        slippage_price_per_side=args.slippage_price_per_side,
    )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    if not result["reference_matched"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
