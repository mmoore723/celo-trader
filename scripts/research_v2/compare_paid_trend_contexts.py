#!/usr/bin/env python3
"""Find stable *entry context* for paid TSLA V2 Trend Continuation quotes.

All candidates use the identical causal Trend Continuation signal and the
same fixed 90-minute option markout.  They differ only by predeclared,
observable context: direction or time of the completed signal.  The earlier
part of the paid archive selects one context; the later part is left untouched
until that selection is made.  This searches for a repeatable pattern without
pretending an in-sample winner is a production edge.
"""

from __future__ import annotations

import argparse
from datetime import date, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.models import Side, Signal
from research_v2.option_markouts import run_databento_cbbo_markouts_for_labeled_signals, strategy_signals
from research_v2.strategies import TrendContinuation
from scripts.research_v2.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file, result_row, write_checkpoint,
)
from scripts.research_v2.tune_paid_orb_holds import segmented_summary


def _in_window(signal: Signal, start: time, end: time) -> bool:
    return start <= signal.timestamp.time() < end


def contexts(signals: tuple[Signal, ...]) -> dict[str, tuple[Signal, ...]]:
    """Return only the six contexts declared before this paid run."""
    return {
        "baseline_all": signals,
        "long_only": tuple(s for s in signals if s.side is Side.LONG),
        "short_only": tuple(s for s in signals if s.side is Side.SHORT),
        "morning_10_15_11_30": tuple(s for s in signals if _in_window(s, time(10, 15), time(11, 30))),
        "midday_11_30_13_30": tuple(s for s in signals if _in_window(s, time(11, 30), time(13, 30))),
        "afternoon_13_30_15_00": tuple(s for s in signals if _in_window(s, time(13, 30), time(15, 0))),
    }


def select_context(markouts: dict[str, list[dict[str, object]]], holdout_start: date) -> dict[str, object]:
    summaries = {name: segmented_summary(rows, holdout_start) for name, rows in markouts.items()}
    eligible = [name for name, summary in summaries.items()
                if int(summary["training"]["measured_signals"]) >= 20]
    if not eligible:
        return {"selected_context": None, "reason": "too_few_training_signals", "summaries": summaries}
    winner = max(
        eligible,
        key=lambda name: (
            float(summaries[name]["training"]["average_return_pct"] or float("-inf")),
            int(summaries[name]["training"]["measured_signals"]),
            -list(markouts).index(name),
        ),
    )
    holdout = summaries[winner]["holdout"]
    passed = (int(holdout["measured_signals"]) >= 10
              and float(holdout["average_return_pct"] or 0.0) > 0.0)
    return {
        "selected_context": winner,
        "selection_rule": "highest average return in earlier data; ties use more signals then declared order",
        "holdout_gate": "at least 10 later signals and positive average return",
        "holdout_passed": passed,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--ticker", default="TSLA")
    # Preserve the independent later segment already reserved by the paid
    # Trend hold-time study.  Do not reclaim any of those dates as training
    # merely because this experiment asks a different entry-context question.
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 5, 19))
    parser.add_argument("--hold-minutes", type=int, default=90)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=.80)
    parser.add_argument("--max-premium", type=float, default=10.0)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument(
        "--max-signals-per-day",
        type=int,
        default=0,
        help="Optional daily cap; 0 evaluates every valid signal (the default).",
    )
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    if args.hold_minutes < 1 or args.max_signals_per_day < 0 or not args.archive.is_file():
        parser.error("a positive hold, non-negative daily cap, and existing paid archive are required")

    dataset = load_csv(args.bars)
    filenames = archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    names = tuple(contexts(()))
    markouts = {name: list(existing.get("markouts_by_context", {}).get(name, [])) for name in names}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Predeclared TSLA V2 Trend Continuation context test using already-paid option quotes; research-only.",
        "data_source": f"local paid portal archive: {args.archive}",
        "ticker": args.ticker.upper(), "strategy": TrendContinuation.strategy_id,
        "execution": "entry at observed ask; same-contract exit at observed bid; no midpoint or synthetic option price",
        "hold_minutes": args.hold_minutes, "max_signals_per_day": args.max_signals_per_day,
        "holdout_start": args.holdout_start.isoformat(),
        "contexts": list(names), "candidate_files": len(filenames),
        "selection_protocol": "Select on earlier data only, then disclose the untouched later result.",
    }

    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        assert trading_day is not None
        bars = day_bars(dataset, trading_day)
        signals = strategy_signals(bars, TrendContinuation()) if bars else ()
        if args.max_signals_per_day:
            signals = signals[:args.max_signals_per_day]
        labeled = contexts(signals)
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
            completed.add(filename)
        elif not signals:
            skipped.append({"filename": filename, "reason": "no_strategy_signal"})
            completed.add(filename)
        else:
            raw_path: Path | None = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                results = run_databento_cbbo_markouts_for_labeled_signals(
                    bars, [raw_path], labeled, args.ticker, hold_minutes=args.hold_minutes,
                    min_dte=args.min_dte, max_dte=args.max_dte, min_premium=args.min_premium,
                    max_premium=args.max_premium, max_spread_pct=args.max_spread_pct,
                )
                for name, rows in results.items():
                    markouts[name].extend(result_row(row) for row in rows)
                completed.add(filename)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)

        selection = select_context(markouts, args.holdout_start)
        write_checkpoint(args.output, {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "markouts_by_context": markouts, "selection": selection,
            "complete": len(completed) == len(filenames),
        })
        processed = len(completed)
        if processed == len(filenames) or (args.progress_every and processed % args.progress_every == 0):
            print(json.dumps({"processed": processed, "candidate_files": len(filenames),
                              "selected_context": selection["selected_context"], "latest_file": filename}), flush=True)

    # A completed checkpoint can be reopened with a different *predeclared*
    # split for inspection without unpacking the archive again.  Always write
    # the final selection so it is not stranded in an earlier checkpoint.
    selection = select_context(markouts, args.holdout_start)
    write_checkpoint(args.output, {
        **base, "processed_files": sorted(completed), "skipped_files": skipped,
        "markouts_by_context": markouts, "selection": selection,
        "complete": len(completed) == len(filenames),
    })


if __name__ == "__main__":
    main()
