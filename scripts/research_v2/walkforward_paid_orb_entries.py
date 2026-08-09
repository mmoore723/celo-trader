#!/usr/bin/env python3
"""Walk-forward-check predeclared V2 ORB entries using saved paid TSLA quotes.

This reads the completed ``compare_paid_orb_entries.py`` report.  It never
opens the paid archive, talks to a broker, changes a strategy flag, or issues
an order.  At the start of each calendar month it chooses the entry setting
with the best *prior* observed ask-to-bid return, then records that choice's
outcome during the following month.  That mimics the information that would
actually have existed at the time and prevents a later good month from
selecting its own rule.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime
import json
from pathlib import Path
from statistics import median


def signal_date(row: dict[str, object]) -> date:
    return datetime.fromisoformat(str(row["signal_time"])).date()


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(row["return_pct"]) for row in rows]
    count = len(returns)
    return {
        "measured_signals": count,
        "positive_markouts": sum(value > 0.0 for value in returns),
        "win_rate_pct": round(100 * sum(value > 0.0 for value in returns) / count, 2) if count else None,
        "average_return_pct": round(sum(returns) / count, 4) if count else None,
        "median_return_pct": round(median(returns), 4) if count else None,
        "total_return_pct": round(sum(returns), 4),
        "worst_return_pct": round(min(returns), 4) if count else None,
        "best_return_pct": round(max(returns), 4) if count else None,
    }


def select_prior_winner(
    markouts: dict[str, list[dict[str, object]]],
    month_start: date,
    candidate_order: list[str],
    minimum_training_signals: int,
) -> tuple[str | None, dict[str, dict[str, object]]]:
    prior = {
        name: [row for row in rows if signal_date(row) < month_start]
        for name, rows in markouts.items()
    }
    summaries = {name: summarize(rows) for name, rows in prior.items()}
    eligible = [
        name for name in candidate_order
        if int(summaries[name]["measured_signals"]) >= minimum_training_signals
    ]
    if not eligible:
        return None, summaries
    winner = max(
        eligible,
        key=lambda name: (
            float(summaries[name]["average_return_pct"] or float("-inf")),
            int(summaries[name]["measured_signals"]),
            -candidate_order.index(name),
        ),
    )
    return winner, summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="Completed paid_tsla_orb_entry_rules.json report")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-training-signals", type=int, default=15)
    parser.add_argument("--baseline", default="baseline")
    args = parser.parse_args()
    if args.min_training_signals < 1:
        parser.error("min-training-signals must be positive")

    source = json.loads(args.input.read_text())
    raw = source.get("markouts_by_entry")
    candidates = source.get("candidates")
    if not isinstance(raw, dict) or not isinstance(candidates, dict):
        raise ValueError("input is not a completed paid entry-comparison report")
    candidate_order = list(candidates)
    if args.baseline not in candidate_order:
        parser.error(f"baseline {args.baseline!r} is not an input candidate")
    markouts = {name: list(raw.get(name, [])) for name in candidate_order}
    all_months = sorted({month_key(signal_date(row)) for rows in markouts.values() for row in rows})

    folds: list[dict[str, object]] = []
    selected_rows: list[dict[str, object]] = []
    baseline_rows: list[dict[str, object]] = []
    selection_counts: dict[str, int] = defaultdict(int)
    skipped_months: list[dict[str, object]] = []
    for month in all_months:
        year, number = (int(part) for part in month.split("-"))
        start = date(year, number, 1)
        selected, prior = select_prior_winner(
            markouts, start, candidate_order, args.min_training_signals,
        )
        if selected is None:
            skipped_months.append({
                "month": month,
                "reason": "too_few_prior_measured_signals",
                "prior_counts": {name: summary["measured_signals"] for name, summary in prior.items()},
            })
            continue
        chosen = [row for row in markouts[selected] if month_key(signal_date(row)) == month]
        baseline = [row for row in markouts[args.baseline] if month_key(signal_date(row)) == month]
        selected_rows.extend(chosen)
        baseline_rows.extend(baseline)
        selection_counts[selected] += 1
        folds.append({
            "month": month,
            "selected_entry": selected,
            "selection_rule": "highest average actual ask-to-bid return using only earlier rows; ties more rows then predeclared order",
            "prior_summary_for_selected": prior[selected],
            "out_of_sample_selected": summarize(chosen),
            "out_of_sample_baseline": summarize(baseline),
        })

    payload = {
        "purpose": "Expanding-window walk-forward validation of predeclared V2 ORB entry settings using saved paid TSLA option quotes; research-only.",
        "source_report": str(args.input),
        "ticker": source.get("ticker"),
        "strategy": source.get("strategy"),
        "execution": source.get("execution"),
        "exit": source.get("fixed_exit"),
        "eligibility": source.get("eligibility"),
        "selection_protocol": {
            "rule": "At each month start, choose the setting with the best average return from earlier months only.",
            "minimum_prior_measured_signals": args.min_training_signals,
            "baseline_comparator": args.baseline,
            "important_limit": "This is a robustness check, not a production-promotion rule or proof of future profitability.",
        },
        "candidate_definitions": candidates,
        "walkforward_folds": folds,
        "skipped_months": skipped_months,
        "selected_entry_month_counts": dict(selection_counts),
        "aggregate_out_of_sample_selected": summarize(selected_rows),
        "aggregate_out_of_sample_baseline": summarize(baseline_rows),
        "complete": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({
        "folds": len(folds),
        "skipped_months": len(skipped_months),
        "selected": payload["aggregate_out_of_sample_selected"],
        "baseline": payload["aggregate_out_of_sample_baseline"],
        "entry_month_counts": dict(selection_counts),
    }, indent=2))


if __name__ == "__main__":
    main()
