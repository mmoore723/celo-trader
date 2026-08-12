#!/usr/bin/env python3
"""Choose a fixed direction/time context from paid markouts, then grade later data.

This is deliberately a small, predeclared tuning pass.  It does *not* change
the entry rule, exit rule, bot settings, or source data.  It chooses among the
same complete-bar signals that were already measured at the real option ask
and bid.  The selected context is based only on the earlier segment, then
reported separately on later untouched sessions.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.jobs.summarize_paid_markouts_holdout import metrics, partition


# These are intentionally broad, understandable contexts.  They are declared
# here before seeing the later data; this is not a parameter-search grid.
CONTEXTS = (
    ("all", None, None, None),
    # ``OptionMarkout.side`` is serialized from ``Side.value`` (lowercase).
    # Matching the enum display name here silently produced zero directional
    # rows and left only the misleading ``all`` bucket eligible.
    ("long_all_day", "long", None, None),
    ("short_all_day", "short", None, None),
    ("long_morning", "long", time(9, 35), time(10, 30)),
    ("short_morning", "short", time(9, 35), time(10, 30)),
    ("long_late_morning", "long", time(10, 35), time(12, 0)),
    ("short_late_morning", "short", time(10, 35), time(12, 0)),
    ("long_afternoon", "long", time(12, 5), time(14, 30)),
    ("short_afternoon", "short", time(12, 5), time(14, 30)),
)


def context_rows(rows: list[dict[str, object]], context: tuple[str, str | None, time | None, time | None]) -> list[dict[str, object]]:
    """Return rows matching one predeclared direction/time context."""
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


def choose_context(rows: list[dict[str, object]], cutoff: date, minimum_training_trades: int) -> dict[str, object]:
    """Select by training average only, then disclose untouched later metrics."""
    training_all = partition(rows, cutoff, True)
    later_all = partition(rows, cutoff, False)
    candidates = []
    for context in CONTEXTS:
        train = context_rows(training_all, context)
        later = context_rows(later_all, context)
        train_metrics = metrics(train)
        later_metrics = metrics(later)
        candidates.append({"context": context[0], "training": train_metrics, "later": later_metrics})

    eligible = [item for item in candidates if int(item["training"]["trades"]) >= minimum_training_trades]
    if not eligible:
        return {"selected_context": None, "reason": "too_few_training_trades", "candidates": candidates}
    selected = max(
        eligible,
        key=lambda item: (
            float(item["training"]["average_return_pct"] or float("-inf")),
            float(item["training"]["profit_factor"] or float("inf")),
            int(item["training"]["trades"]),
        ),
    )
    later = selected["later"]
    passes = (
        int(later["trades"]) >= 10
        and float(later["average_return_pct"] or 0) > 0
        and (later["profit_factor"] is None or float(later["profit_factor"]) > 1)
    )
    return {
        "selected_context": selected["context"],
        "selection_rule": "highest earlier-period average return; ties use profit factor then more trades",
        "later_gate": "at least 10 later trades, positive later average, and profit factor above 1 when losses exist",
        "later_passed": passes,
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--minimum-training-trades", type=int, default=20)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not payload.get("complete"):
        raise ValueError("input study is incomplete; do not tune a partial run")
    rows = payload.get("markouts")
    if not isinstance(rows, list):
        raise ValueError("input study has no markouts")
    result = {
        "purpose": "Predeclared paid-markout direction/time selection using earlier data only.",
        "source_study": str(args.input),
        "ticker": payload.get("ticker"), "strategy": payload.get("strategy"),
        "holdout_start": args.holdout_start.isoformat(),
        "selection": choose_context(rows, args.holdout_start, args.minimum_training_trades),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected_context": result["selection"]["selected_context"],
                      "later_passed": result["selection"].get("later_passed")}, indent=2))


if __name__ == "__main__":
    main()
