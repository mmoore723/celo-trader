#!/usr/bin/env python3
"""Judge one fixed paid option-quote strategy against untouched later dates.

This is for a *single, already-fixed* strategy configuration.  It never tunes
parameters, fetches data, talks to a broker, or changes the paper bot.  It
exists so an affordable-contract study cannot be called profitable merely
because its full-history average happened to be positive.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def partition(rows: list[dict[str, object]], cutoff: date, before: bool) -> list[dict[str, object]]:
    """Split rows by signal day; the cutoff day belongs to the final exam."""
    return [
        row for row in rows
        if (datetime.fromisoformat(str(row["signal_time"])).date() < cutoff) is before
    ]


def metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(row["return_pct"]) for row in rows]
    if not returns:
        return {
            "trades": 0, "average_return_pct": None, "median_return_pct": None,
            "win_rate_pct": None, "profit_factor": None,
        }
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    ordered = sorted(returns)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    loss_total = -sum(losses)
    return {
        "trades": len(returns),
        "average_return_pct": round(sum(returns) / len(returns), 4),
        "median_return_pct": round(median, 4),
        "win_rate_pct": round(len(wins) / len(returns) * 100, 2),
        "profit_factor": round(sum(wins) / loss_total, 4) if loss_total else None,
    }


def assess(rows: list[dict[str, object]], holdout_start: date, min_holdout_trades: int = 10) -> dict[str, object]:
    """Return a predeclared go/no-go result without choosing any rule."""
    training = metrics(partition(rows, holdout_start, True))
    holdout = metrics(partition(rows, holdout_start, False))
    profit_factor = holdout["profit_factor"]
    passes = (
        int(holdout["trades"]) >= min_holdout_trades
        and float(holdout["average_return_pct"] or 0.0) > 0.0
        and (profit_factor is None or float(profit_factor) > 1.0)
    )
    return {
        "decision": "paper_candidate" if passes else "reject",
        "gate": "at least 10 later trades, positive later average return, and profit factor above 1 when losses exist",
        "training": training,
        "holdout": holdout,
        "important_limit": "A paper candidate is not a guarantee. It still requires prospective paper evidence and realistic account-level sizing.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Completed run_paid_databento_job JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--min-holdout-trades", type=int, default=10)
    args = parser.parse_args()
    if args.min_holdout_trades < 1:
        parser.error("min-holdout-trades must be positive")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not payload.get("complete"):
        raise ValueError("input study is incomplete; do not judge a partial run")
    rows = payload.get("markouts")
    if not isinstance(rows, list):
        raise ValueError("input study has no markouts")
    report = {
        "purpose": "Read-only final-exam check for one fixed, paid option quote-to-quote strategy.",
        "source_study": str(args.input),
        "ticker": payload.get("ticker"), "strategy": payload.get("strategy"),
        "holdout_start": args.holdout_start.isoformat(),
        "assessment": assess(rows, args.holdout_start, args.min_holdout_trades),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": report["assessment"]["decision"]}, indent=2))


if __name__ == "__main__":
    main()
