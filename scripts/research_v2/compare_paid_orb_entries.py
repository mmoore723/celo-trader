#!/usr/bin/env python3
"""Compare predeclared V2 ORB entry timing variants using paid TSLA quotes.

This is research only.  It does not alter the router, live strategy flags,
orders, broker configuration, or exit logic.  Every candidate buys the same
style of option at an observed ask and sells the *same* contract at an
observed bid 90 minutes later.
"""
from __future__ import annotations

import argparse
from datetime import date, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.option_markouts import (
    run_databento_cbbo_markouts_for_labeled_signals, strategy_signals,
)
from research_v2.strategies import OpeningRangePullback, OpeningRangePullbackConfig
from scripts.research_v2.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file,
    result_row, write_checkpoint,
)
from scripts.research_v2.tune_paid_orb_holds import segmented_summary


# These variants are declared before looking at their paid-option outcomes.
# The current V2 settings are the explicit baseline; the other variants change
# one entry dimension at a time so results remain explainable to a new trader.
CANDIDATES: dict[str, OpeningRangePullbackConfig] = {
    "baseline": OpeningRangePullbackConfig(),
    "tighter_retest_0_05pct": OpeningRangePullbackConfig(retest_tolerance_pct=0.0005),
    "wider_retest_0_20pct": OpeningRangePullbackConfig(retest_tolerance_pct=0.0020),
    "earlier_window_10_15_10_30": OpeningRangePullbackConfig(
        breakout_deadline=time(10, 15), entry_deadline=time(10, 30),
    ),
    "later_window_10_45_11_00": OpeningRangePullbackConfig(
        breakout_deadline=time(10, 45), entry_deadline=time(11, 0),
    ),
}


def select_training_candidate(
    markouts: dict[str, list[dict[str, object]]], holdout_start: date,
    minimum_training_signals: int = 15,
) -> dict[str, object]:
    """Choose only on the earlier data; disclose untouched later data."""
    summaries = {name: segmented_summary(rows, holdout_start) for name, rows in markouts.items()}
    eligible = [name for name in CANDIDATES
                if int(summaries[name]["training"]["measured_signals"]) >= minimum_training_signals]
    if not eligible:
        return {"selected_entry": None, "reason": "too_few_training_signals", "summaries": summaries}
    winner = max(
        eligible,
        key=lambda name: (
            float(summaries[name]["training"]["average_return_pct"] or float("-inf")),
            int(summaries[name]["training"]["measured_signals"]),
            -list(CANDIDATES).index(name),
        ),
    )
    holdout = summaries[winner]["holdout"]
    passes = (int(holdout["measured_signals"]) >= 10
              and float(holdout["average_return_pct"] or 0.0) > 0.0)
    return {
        "selected_entry": winner,
        "selection_rule": "highest training average return; ties use more signals then earlier predeclared order",
        "holdout_gate": "at least 10 holdout signals and positive average return",
        "holdout_passed": passes,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare predeclared V2 ORB entry variants using paid quotes")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--ticker", default="TSLA")
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--hold-minutes", type=int, default=90)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=0.08)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error(f"archive does not exist: {args.archive}")

    dataset = load_csv(args.bars)
    filenames = archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    raw_markouts = existing.get("markouts_by_entry", {})
    markouts = {name: list(raw_markouts.get(name, [])) for name in CANDIDATES}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)

    base = {
        "purpose": "Predeclared V2 TSLA ORB pullback entry-parameter comparison; research-only.",
        "data_source": f"local paid portal archive: {args.archive}",
        "ticker": args.ticker.upper(), "strategy": "V2_ORB_PULLBACK",
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "fixed_exit": f"{args.hold_minutes}-minute markout; chosen because VWAP/EMA exit comparison did not beat it",
        "holdout_start": args.holdout_start.isoformat(),
        "selection_protocol": "Choose highest training average return, then evaluate its untouched holdout.",
        "candidates": {
            name: {"retest_tolerance_pct": config.retest_tolerance_pct,
                   "breakout_deadline": config.breakout_deadline.isoformat(),
                   "entry_deadline": config.entry_deadline.isoformat()}
            for name, config in CANDIDATES.items()
        },
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
        else:
            raw_path: Path | None = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                signals = {
                    name: strategy_signals(bars, OpeningRangePullback(config))
                    for name, config in CANDIDATES.items()
                }
                # All five hypotheses now share two passes over the large OPRA
                # file: one to select actual ask fills and one to read actual
                # bid exits.  It is exactly the same evidence model as the
                # earlier version, without re-reading the file five times.
                results = run_databento_cbbo_markouts_for_labeled_signals(
                    bars, [raw_path], signals, args.ticker,
                    hold_minutes=args.hold_minutes, min_dte=args.min_dte, max_dte=args.max_dte,
                    min_premium=args.min_premium, max_premium=args.max_premium,
                    max_spread_pct=args.max_spread_pct,
                )
                for name, rows in results.items():
                    markouts[name].extend(result_row(row) for row in rows)
                completed.add(filename)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)

        selection = select_training_candidate(markouts, args.holdout_start)
        write_checkpoint(args.output, {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "markouts_by_entry": markouts, "selection": selection,
            "complete": len(completed) == len(filenames),
        })
        processed = len(completed)
        if (args.progress_every and processed % args.progress_every == 0) or processed == len(filenames):
            print(json.dumps({"processed": processed, "candidate_files": len(filenames),
                              "selected_entry": selection["selected_entry"],
                              "latest_file": filename}, indent=2), flush=True)


if __name__ == "__main__":
    main()
