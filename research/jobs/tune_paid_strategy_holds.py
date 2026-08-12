#!/usr/bin/env python3
"""Compare a distinct paid-quote strategy across fixed exit holds.

Research-only: a local, already-paid OPRA archive is read one session at a
time.  Entries pay the displayed ask and exits receive the displayed bid on
the very same contract.  Three exit lengths are declared before the scan;
the earlier portion chooses one and the later portion judges it untouched.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv, resample_regular_session
from research.engine.option_markouts import run_databento_cbbo_markouts_for_holds, strategy_signals
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, build_strategy, day_bars, day_bars_with_prior_close, extract_archive_file,
    result_row, write_checkpoint,
)


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(row["return_pct"]) for row in rows]
    count = len(returns)
    return {
        "measured_signals": count,
        "positive_markouts": sum(value > 0 for value in returns),
        "win_rate_pct": round(100 * sum(value > 0 for value in returns) / count, 2) if count else None,
        "average_return_pct": round(sum(returns) / count, 4) if count else None,
        "median_return_pct": round(statistics.median(returns), 4) if count else None,
        "total_return_pct": round(sum(returns), 4),
    }


def _before(rows: list[dict[str, object]], cutoff: date, is_training: bool) -> list[dict[str, object]]:
    return [
        row for row in rows
        if (datetime.fromisoformat(str(row["signal_time"])).date() < cutoff) is is_training
    ]


def _segmented(rows: list[dict[str, object]], cutoff: date) -> dict[str, object]:
    return {"all": _summary(rows), "training": _summary(_before(rows, cutoff, True)),
            "holdout": _summary(_before(rows, cutoff, False))}


def non_overlapping_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep the first executable trade until its exit before considering another.

    A markout scanner is naturally useful for examining every signal.  A
    small-account strategy test, however, cannot treat multiple overlapping
    option positions as independently deployable.  This deterministic filter
    models one open position at a time without inventing fills or changing
    the underlying signal rules.
    """
    kept: list[dict[str, object]] = []
    available_at: datetime | None = None
    for row in sorted(rows, key=lambda item: str(item["entry_time"])):
        entry = datetime.fromisoformat(str(row["entry_time"]))
        exit_at = datetime.fromisoformat(str(row["exit_time"]))
        if available_at is not None and entry < available_at:
            continue
        kept.append(row)
        available_at = exit_at
    return kept


def select_robust_hold(
    marks: dict[int, list[dict[str, object]]], holdout_start: date,
    minimum_training_signals: int = 15, minimum_holdout_signals: int = 10,
) -> dict[str, object]:
    """Choose with prior dates only; require typical and average later gains."""
    summaries = {hold: _segmented(rows, holdout_start) for hold, rows in marks.items()}
    eligible = [
        hold for hold, summary in summaries.items()
        if int(summary["training"]["measured_signals"]) >= minimum_training_signals
    ]
    if not eligible:
        return {"selected_hold_minutes": None, "reason": "too_few_training_signals",
                "minimum_training_signals": minimum_training_signals, "summaries": summaries}
    winner = max(eligible, key=lambda hold: (
        float(summaries[hold]["training"]["median_return_pct"] or float("-inf")),
        float(summaries[hold]["training"]["average_return_pct"] or float("-inf")),
        int(summaries[hold]["training"]["measured_signals"]), -hold,
    ))
    train, later = summaries[winner]["training"], summaries[winner]["holdout"]
    passed = (
        int(later["measured_signals"]) >= minimum_holdout_signals
        and float(train["average_return_pct"] or 0) > 0
        and float(train["median_return_pct"] or 0) > 0
        and float(later["average_return_pct"] or 0) > 0
        and float(later["median_return_pct"] or 0) > 0
    )
    return {
        "selected_hold_minutes": winner,
        "selection_rule": "earlier-data highest median return; ties use average, sample size, then shorter hold",
        "holdout_gate": (f"at least {minimum_holdout_signals} later signals and positive average plus median "
                         "return on both earlier and later data"),
        "holdout_passed": passed,
        "minimum_training_signals": minimum_training_signals,
        "minimum_holdout_signals": minimum_holdout_signals,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--strategy",
        choices=("turtle_soup_rth", "gap_fill_rth", "ema_pullback_rth", "fair_value_gap_rth", "midday_breakdown", "trend_continuation", "afternoon_reversal"),
        required=True,
    )
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--hold-minutes", type=int, nargs="+", default=(30, 60, 90))
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=.80)
    parser.add_argument("--max-premium", type=float, default=10.0)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument("--progress-every", type=int, default=5)
    parser.add_argument(
        "--one-position-at-a-time", action="store_true",
        help="Evaluate each hold with non-overlapping executable positions.",
    )
    args = parser.parse_args()
    holds = tuple(sorted(set(args.hold_minutes)))
    if not args.archive.is_dir() or not holds or any(hold < 1 for hold in holds):
        parser.error("an extracted archive and positive hold minutes are required")
    dataset, filenames = load_csv(args.bars), archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    marks = {hold: list(existing.get("markouts_by_hold", {}).get(str(hold), [])) for hold in holds}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Predeclared fixed-hold test for one distinct SPY intraday strategy using local paid OPRA quotes; research-only.",
        "data_source": f"local paid portal archive: {args.archive}", "ticker": args.ticker.upper(),
        "strategy": args.strategy, "hold_minutes_tested": list(holds), "holdout_start": args.holdout_start.isoformat(),
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "bars_path": str(args.bars), "bars_sha256": dataset.sha256, "candidate_files": len(filenames),
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte, "min_premium": args.min_premium,
                        "max_premium": args.max_premium, "max_spread_pct": args.max_spread_pct},
    }
    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        # Gap-reclaim signals need yesterday's close to define today's gap.
        # That prior bar is context only: quotes are still read exclusively
        # from today's already-paid OPRA file, and no signal can be emitted
        # until today's completed bars arrive.
        bars = (
            day_bars_with_prior_close(dataset, trading_day)
            if trading_day and args.strategy == "gap_fill_rth"
            else day_bars(dataset, trading_day) if trading_day else ()
        )
        if bars and args.strategy in {"fair_value_gap_rth", "midday_breakdown", "trend_continuation", "afternoon_reversal"}:
            # These formations are defined from complete five-minute candles;
            # resample only the frozen underlying bars for this day.  Quotes
            # are still selected from the matching current-day OPRA file.
            bars = resample_regular_session(tuple(bars), source_minutes=1, target_minutes=5)
        signals = strategy_signals(bars, build_strategy(args.strategy)) if bars else ()
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
        elif not signals:
            skipped.append({"filename": filename, "reason": "no_strategy_signal"})
        else:
            staged = None
            try:
                staged = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                results = run_databento_cbbo_markouts_for_holds(
                    bars, [staged], build_strategy(args.strategy), underlying=args.ticker, hold_minutes=holds,
                    min_dte=args.min_dte, max_dte=args.max_dte, min_premium=args.min_premium,
                    max_premium=args.max_premium, max_spread_pct=args.max_spread_pct,
                )
                for hold, rows in results.items():
                    marks[hold].extend(result_row(row) for row in rows)
            finally:
                if staged is not None:
                    staged.unlink(missing_ok=True)
        completed.add(filename)
        evaluated_marks = {
            hold: non_overlapping_rows(marks[hold]) if args.one_position_at_a_time else marks[hold]
            for hold in holds
        }
        selection = select_robust_hold(evaluated_marks, args.holdout_start)
        write_checkpoint(args.output, {**base, "processed_files": sorted(completed), "skipped_files": skipped,
            "position_policy": "one_open_position" if args.one_position_at_a_time else "per_signal_diagnostic",
            "markouts_by_hold": {str(hold): evaluated_marks[hold] for hold in holds}, "selection": selection,
            "complete": len(completed) == len(filenames)})
        if len(completed) == len(filenames) or len(completed) % args.progress_every == 0:
            print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                "selected_hold_minutes": selection["selected_hold_minutes"], "latest_file": filename}), flush=True)


if __name__ == "__main__":
    main()
