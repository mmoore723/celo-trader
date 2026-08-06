#!/usr/bin/env python3
"""Predeclared exit-hold study using one already-paid Databento archive.

This script is research-only.  It does not import live settings, contact a
broker, or modify a production strategy.  It evaluates exactly three fixed
holding periods (30/60/90 minutes by default) on an earlier training segment,
then reports the winner on a later untouched segment.  That separation avoids
selecting an exit merely because it happened to fit the whole past year.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.option_markouts import run_databento_cbbo_markouts_for_holds
from research_v2.option_markouts import strategy_signals
from scripts.research_v2.run_paid_databento_job import (
    archive_filenames, batch_file_date, build_strategy, day_bars,
    extract_archive_file, result_row, summarize, write_checkpoint,
)


def _rows_before(rows: list[dict[str, object]], cutoff: date, before: bool) -> list[dict[str, object]]:
    """Partition by signal date; the holdout date itself is never training."""
    return [row for row in rows if (datetime.fromisoformat(str(row["signal_time"])).date() < cutoff) is before]


def segmented_summary(rows: list[dict[str, object]], holdout_start: date) -> dict[str, object]:
    return {
        "all": summarize(rows),
        "training": summarize(_rows_before(rows, holdout_start, True)),
        "holdout": summarize(_rows_before(rows, holdout_start, False)),
    }


def select_training_winner(
    markouts_by_hold: dict[int, list[dict[str, object]]], holdout_start: date,
    minimum_training_signals: int = 15,
) -> dict[str, object]:
    """Select only from training, then disclose—not optimize—the holdout."""
    summaries = {hold: segmented_summary(rows, holdout_start) for hold, rows in markouts_by_hold.items()}
    eligible = [
        hold for hold, item in summaries.items()
        if int(item["training"]["measured_signals"]) >= minimum_training_signals
    ]
    if not eligible:
        return {"selected_hold_minutes": None, "reason": "too_few_training_signals", "summaries": summaries}
    winner = max(
        eligible,
        key=lambda hold: (
            float(summaries[hold]["training"]["average_return_pct"] or float("-inf")),
            int(summaries[hold]["training"]["measured_signals"]),
            -hold,
        ),
    )
    holdout = summaries[winner]["holdout"]
    passes = (
        int(holdout["measured_signals"]) >= 10
        and float(holdout["average_return_pct"] or 0.0) > 0.0
    )
    return {
        "selected_hold_minutes": winner,
        "selection_rule": "highest average return on training only; ties use more signals then shorter hold",
        "holdout_gate": "at least 10 holdout signals and positive average return",
        "holdout_passed": passes,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune one predeclared V2 ORB exit dimension using paid bid/ask data")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--ticker", default="TSLA")
    parser.add_argument("--strategy", choices=("orb_pullback",), default="orb_pullback")
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--hold-minutes", type=int, nargs="+", default=(30, 60, 90))
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=0.08)
    args = parser.parse_args()

    holds = tuple(sorted(set(args.hold_minutes)))
    if not holds or any(hold < 1 for hold in holds):
        parser.error("hold-minutes must contain positive unique values")
    if not args.archive.is_file():
        parser.error(f"archive does not exist: {args.archive}")
    dataset = load_csv(args.bars)
    filenames = archive_filenames(args.archive)
    if not filenames:
        raise RuntimeError("archive contains no daily CBBO files")

    existing: dict[str, object] = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    raw_markouts = existing.get("markouts_by_hold", {})
    markouts_by_hold: dict[int, list[dict[str, object]]] = {
        hold: list(raw_markouts.get(str(hold), [])) for hold in holds
    }
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)

    base = {
        "purpose": "Predeclared V2 TSLA ORB pullback hold-time study; research-only, never a broker command.",
        "data_source": f"local paid portal archive: {args.archive}",
        "ticker": args.ticker.upper(), "strategy": args.strategy,
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "bars_path": str(args.bars), "bars_sha256": dataset.sha256,
        "hold_minutes_tested": list(holds), "holdout_start": args.holdout_start.isoformat(),
        "selection_protocol": "Choose highest training average return, then evaluate its untouched holdout.",
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte,
                        "min_premium": args.min_premium, "max_premium": args.max_premium,
                        "max_spread_pct": args.max_spread_pct},
        "candidate_files": len(filenames),
    }

    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        assert trading_day is not None
        bars = day_bars(dataset, trading_day)
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
            completed.add(filename)
        elif not strategy_signals(bars, build_strategy(args.strategy)):
            # Most sessions have no qualifying V2 signal.  There is no reason
            # to unpack and scan a 40–60 MB option-chain file just to discover
            # that there cannot be an entry on that date.
            skipped.append({"filename": filename, "reason": "no_strategy_signal"})
            completed.add(filename)
        else:
            raw_path: Path | None = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                results_by_hold = run_databento_cbbo_markouts_for_holds(
                    bars, [raw_path], build_strategy(args.strategy), underlying=args.ticker,
                    hold_minutes=holds, min_dte=args.min_dte, max_dte=args.max_dte,
                    min_premium=args.min_premium, max_premium=args.max_premium,
                    max_spread_pct=args.max_spread_pct,
                )
                for hold, results in results_by_hold.items():
                    markouts_by_hold[hold].extend(result_row(result) for result in results)
                completed.add(filename)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)

        selection = select_training_winner(markouts_by_hold, args.holdout_start)
        payload: dict[str, object] = {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "markouts_by_hold": {str(hold): markouts_by_hold[hold] for hold in holds},
            "selection": selection, "complete": len(completed) == len(filenames),
        }
        write_checkpoint(args.output, payload)
        print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                          "selected_hold_minutes": selection["selected_hold_minutes"],
                          "latest_file": filename}, indent=2), flush=True)


if __name__ == "__main__":
    main()
