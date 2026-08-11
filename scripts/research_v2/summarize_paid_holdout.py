#!/usr/bin/env python3
"""Create a plain-English robustness audit for a completed paid hold study.

This command intentionally reads an immutable completed research result.  It
does not select new parameters, query a data vendor, contact a broker, or
change application settings.  Its job is to make the final train/final-exam
decision understandable before a strategy can be considered for paper use.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.research_v2.tune_paid_orb_holds import select_training_winner


def _partition(rows: list[dict[str, object]], cutoff: date, before: bool) -> list[dict[str, object]]:
    return [
        row for row in rows
        if (datetime.fromisoformat(str(row["signal_time"])).date() < cutoff) is before
    ]


def _metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(row["return_pct"]) for row in rows]
    if not returns:
        return {"trades": 0, "average_return_pct": None, "median_return_pct": None,
                "win_rate_pct": None, "profit_factor": None, "average_win_pct": None,
                "average_loss_pct": None, "max_cumulative_drawdown_pct": None,
                "max_consecutive_losses": 0, "top_five_contribution_pct": None,
                "average_without_top_five_pct": None}
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    gross_loss = -sum(losses)
    equity = peak = 0.0
    max_drawdown = 0.0
    streak = max_streak = 0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
        if value <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    ordered = sorted(returns, reverse=True)
    top = ordered[:5]
    remaining = ordered[5:]
    middle = sorted(returns)
    median = middle[len(middle) // 2] if len(middle) % 2 else (middle[len(middle) // 2 - 1] + middle[len(middle) // 2]) / 2
    return {
        "trades": len(returns),
        "average_return_pct": round(sum(returns) / len(returns), 4),
        "median_return_pct": round(median, 4),
        "win_rate_pct": round(len(wins) / len(returns) * 100, 2),
        "profit_factor": round(sum(wins) / gross_loss, 4) if gross_loss else None,
        "average_win_pct": round(sum(wins) / len(wins), 4) if wins else None,
        "average_loss_pct": round(sum(losses) / len(losses), 4) if losses else None,
        "max_cumulative_drawdown_pct": round(max_drawdown, 4),
        "max_consecutive_losses": max_streak,
        "top_five_contribution_pct": round(sum(top), 4),
        "average_without_top_five_pct": round(sum(remaining) / len(remaining), 4) if remaining else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a completed paid quote holdout study")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not payload.get("complete"):
        raise ValueError("input study is incomplete; do not judge a partial run")
    raw = payload.get("markouts_by_hold")
    if not isinstance(raw, dict):
        raise ValueError("input has no markouts_by_hold")
    holdout_start = date.fromisoformat(str(payload["holdout_start"]))
    rows_by_hold = {int(hold): list(rows) for hold, rows in raw.items()}
    selection = select_training_winner(rows_by_hold, holdout_start)
    chosen = selection.get("selected_hold_minutes")
    if chosen is None:
        audit: dict[str, object] = {"decision": "reject", "reason": selection.get("reason")}
    else:
        rows = rows_by_hold[int(chosen)]
        training = _metrics(_partition(rows, holdout_start, True))
        holdout = _metrics(_partition(rows, holdout_start, False))
        passed = bool(selection.get("holdout_passed"))
        audit = {
            "decision": "paper_candidate" if passed else "reject",
            "reason": "training-selected hold passed untouched final-exam gate" if passed
                      else "training-selected hold failed untouched final-exam gate",
            "selected_hold_minutes": chosen,
            "training": training,
            "holdout": holdout,
            "important_limit": "A paper candidate is not a promise of profitability. It still requires prospective paper evidence.",
        }
    report = {
        "purpose": "Read-only robustness audit of completed actual option bid/ask research.",
        "source_study": str(args.input),
        "ticker": payload.get("ticker"),
        "strategy": payload.get("strategy"),
        "holdout_start": holdout_start.isoformat(),
        "selection": selection,
        "audit": audit,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": audit["decision"], "selected_hold_minutes": audit.get("selected_hold_minutes")}, indent=2))


if __name__ == "__main__":
    main()
