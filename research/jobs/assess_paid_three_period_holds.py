#!/usr/bin/env python3
"""Choose a fixed option hold in May, verify it in June, then grade July.

The source report contains real ask-entry / same-contract-bid-exit markouts
for several predeclared hold lengths.  This script is read-only: it does not
rescan an archive, change strategy rules, or talk to the bot.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.jobs.summarize_paid_markouts_holdout import metrics


def _day(row: dict[str, object]) -> date:
    return datetime.fromisoformat(str(row["signal_time"])).date()


def _period(rows: list[dict[str, object]], start: date, end: date | None) -> list[dict[str, object]]:
    return [row for row in rows if _day(row) >= start and (end is None or _day(row) < end)]


def _positive(summary: dict[str, object], minimum: int) -> bool:
    return (int(summary["trades"]) >= minimum
            and float(summary["average_return_pct"] or 0) > 0
            and float(summary["median_return_pct"] or 0) > 0)


def assess_three_period_holds(
    marks: dict[int, list[dict[str, object]]],
    selection_start: date = date(2026, 5, 1),
    validation_start: date = date(2026, 6, 1),
    holdout_start: date = date(2026, 7, 1),
    minimum_selection_trades: int = 15,
    minimum_later_trades: int = 10,
) -> dict[str, object]:
    """Choose a hold on May only; June and July never participate in choice."""
    candidates = []
    for hold in sorted(marks):
        rows = marks[hold]
        candidates.append({
            "hold_minutes": hold,
            "selection_may": metrics(_period(rows, selection_start, validation_start)),
            "validation_june": metrics(_period(rows, validation_start, holdout_start)),
            "holdout_july": metrics(_period(rows, holdout_start, None)),
        })
    eligible = [item for item in candidates if _positive(item["selection_may"], minimum_selection_trades)]
    if not eligible:
        return {"selected_hold_minutes": None, "decision": "reject",
                "reason": "no_hold_had_positive_average_and_median_with_enough_may_trades",
                "candidates": candidates}
    selected = max(eligible, key=lambda item: (
        float(item["selection_may"]["median_return_pct"] or float("-inf")),
        float(item["selection_may"]["average_return_pct"] or float("-inf")),
        int(item["selection_may"]["trades"]),
        -item["hold_minutes"],
    ))
    june_passed = _positive(selected["validation_june"], minimum_later_trades)
    july_passed = _positive(selected["holdout_july"], minimum_later_trades)
    return {
        "selected_hold_minutes": selected["hold_minutes"],
        "selection_rule": "May only: highest median return; ties use average, sample size, then shorter hold",
        "validation_gate": f"June and July each need at least {minimum_later_trades} trades plus positive average and median returns",
        "june_passed": june_passed, "july_passed": july_passed,
        "decision": "paper_candidate" if june_passed and july_passed else "reject",
        "selected_metrics": {key: selected[key] for key in ("selection_may", "validation_june", "holdout_july")},
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-selection-trades", type=int, default=15)
    parser.add_argument("--minimum-later-trades", type=int, default=10)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not payload.get("complete"):
        raise ValueError("input study is incomplete; do not assess a partial scan")
    raw_marks = payload.get("markouts_by_hold")
    if not isinstance(raw_marks, dict):
        raise ValueError("input study has no hold markouts")
    marks = {int(hold): rows for hold, rows in raw_marks.items() if isinstance(rows, list)}
    report = {
        "purpose": "Three-period fixed-hold assessment using already-paid option ask-to-bid markouts; research-only.",
        "source_study": str(args.input), "ticker": payload.get("ticker"), "strategy": payload.get("strategy"),
        "selection_period": "May 2026", "validation_period": "June 2026", "holdout_period": "July 2026",
        "assessment": assess_three_period_holds(marks, minimum_selection_trades=args.minimum_selection_trades,
                                                  minimum_later_trades=args.minimum_later_trades),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report["assessment"].get(key) for key in
                      ("selected_hold_minutes", "june_passed", "july_passed", "decision")}, indent=2))


if __name__ == "__main__":
    main()
