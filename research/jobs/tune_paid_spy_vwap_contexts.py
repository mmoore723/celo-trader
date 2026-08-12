#!/usr/bin/env python3
"""Tune a small, causal time/direction gate for paid SPY VWAP pullbacks.

This is deliberately a *three-period* test.  May chooses a single context,
June checks whether it holds up, and July is a final untouched score.  It
reuses the already measured ask-to-bid option markouts; it neither downloads
data nor alters the bot.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.jobs.summarize_paid_markouts_holdout import metrics


# A few named, readable contexts—not a broad parameter search.  Each is
# knowable when the one-minute signal arrives and does not cap daily trades.
CONTEXTS = (
    ("all_vwap_pullbacks", None, None, None),
    ("morning_vwap_pullbacks", None, time(10, 0), time(10, 59)),
    ("late_morning_vwap_pullbacks", None, time(11, 0), time(11, 59)),
    ("midday_vwap_pullbacks", None, time(12, 0), time(12, 59)),
    ("afternoon_vwap_pullbacks", None, time(13, 0), time(14, 30)),
    ("long_late_morning", "long", time(11, 0), time(11, 59)),
    ("short_late_morning", "short", time(11, 0), time(11, 59)),
    ("long_afternoon", "long", time(13, 0), time(14, 30)),
    ("short_afternoon", "short", time(13, 0), time(14, 30)),
)


def _day(row: dict[str, object]) -> date:
    return datetime.fromisoformat(str(row["signal_time"])).date()


def context_rows(rows: list[dict[str, object]], context: tuple[str, str | None, time | None, time | None]) -> list[dict[str, object]]:
    """Filter on attributes available at the completed one-minute signal."""
    _, side, start, end = context
    selected = []
    for row in rows:
        stamp = datetime.fromisoformat(str(row["signal_time"]))
        if side is not None and row.get("side") != side:
            continue
        if start is not None and not (start <= stamp.time() <= end):
            continue
        selected.append(row)
    return selected


def _period(rows: list[dict[str, object]], start: date, end: date) -> list[dict[str, object]]:
    return [row for row in rows if start <= _day(row) < end]


def _positive(summary: dict[str, object], minimum: int) -> bool:
    return (int(summary["trades"]) >= minimum
            and float(summary["average_return_pct"] or 0) > 0
            and float(summary["median_return_pct"] or 0) > 0)


def select_three_period_context(
    rows: list[dict[str, object]],
    selection_start: date = date(2026, 5, 1),
    validation_start: date = date(2026, 6, 1),
    holdout_start: date = date(2026, 7, 1),
    minimum_selection_trades: int = 10,
    minimum_later_trades: int = 10,
) -> dict[str, object]:
    """Choose on May, validate June, and disclose July without re-selection."""
    selection_rows = _period(rows, selection_start, validation_start)
    validation_rows = _period(rows, validation_start, holdout_start)
    holdout_rows = [row for row in rows if _day(row) >= holdout_start]
    candidates = []
    for context in CONTEXTS:
        candidates.append({
            "context": context[0],
            "selection_may": metrics(context_rows(selection_rows, context)),
            "validation_june": metrics(context_rows(validation_rows, context)),
            "holdout_july": metrics(context_rows(holdout_rows, context)),
        })
    eligible = [item for item in candidates if _positive(item["selection_may"], minimum_selection_trades)]
    if not eligible:
        return {
            "selected_context": None,
            "decision": "reject",
            "reason": "no_context_had_positive_average_and_median_with_enough_may_trades",
            "candidates": candidates,
        }
    selected = max(eligible, key=lambda item: (
        float(item["selection_may"]["median_return_pct"] or float("-inf")),
        float(item["selection_may"]["average_return_pct"] or float("-inf")),
        int(item["selection_may"]["trades"]),
        -[entry[0] for entry in CONTEXTS].index(item["context"]),
    ))
    june_passed = _positive(selected["validation_june"], minimum_later_trades)
    july_passed = _positive(selected["holdout_july"], minimum_later_trades)
    return {
        "selected_context": selected["context"],
        "selection_rule": "May only: highest median option return; ties use average return, sample size, then declared order",
        "validation_gate": f"June and July each need at least {minimum_later_trades} trades plus positive average and median returns",
        "june_passed": june_passed,
        "july_passed": july_passed,
        "decision": "paper_candidate" if june_passed and july_passed else "reject",
        "selected_metrics": {key: selected[key] for key in ("selection_may", "validation_june", "holdout_july")},
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", default="base")
    parser.add_argument("--minimum-selection-trades", type=int, default=10)
    parser.add_argument("--minimum-later-trades", type=int, default=10)
    args = parser.parse_args()
    if args.minimum_selection_trades < 1 or args.minimum_later_trades < 1:
        parser.error("minimum trade counts must be positive")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not payload.get("complete"):
        raise ValueError("input study is incomplete; do not tune a partial run")
    rows = payload.get("markouts_by_variant", {}).get(args.variant)
    if not isinstance(rows, list):
        raise ValueError(f"input study has no {args.variant!r} markouts")
    report = {
        "purpose": "Three-period, causal SPY VWAP context selection using already-paid option ask-to-bid markouts; research-only.",
        "source_study": str(args.input), "ticker": payload.get("ticker"), "strategy": payload.get("strategy"),
        "variant": args.variant, "selection_period": "May 2026", "validation_period": "June 2026", "holdout_period": "July 2026",
        "no_daily_trade_cap": True,
        "selection": select_three_period_context(rows, minimum_selection_trades=args.minimum_selection_trades,
                                                   minimum_later_trades=args.minimum_later_trades),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report["selection"].get(key) for key in ("selected_context", "june_passed", "july_passed", "decision")}, indent=2))


if __name__ == "__main__":
    main()
