#!/usr/bin/env python3
"""Test RSI/MACD confirmation filters against already-paid TSLA option quotes.

This does not alter the bot.  The base setup, RSI-only, MACD-only, and both
filters are declared before their real ask-to-bid option outcomes are read.
All candidates share the same two scans of each daily OPRA file.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.indicators import confirmed_signals
from research.engine.option_markouts import run_databento_cbbo_markouts_for_labeled_signals, strategy_signals
from research.engine.strategies import OpeningRangePullback, OpeningRangePullbackConfig, TrendContinuation
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file, result_row, write_checkpoint,
)
from research.jobs.tune_paid_orb_holds import segmented_summary


VARIANTS = ("base", "rsi_14_aligned", "macd_12_26_9_aligned", "rsi_and_macd_aligned")


def base_strategy(name: str):
    if name == "v2_orb_pullback":
        return OpeningRangePullback(OpeningRangePullbackConfig(retest_tolerance_pct=0.0005))
    if name == "trend_continuation":
        return TrendContinuation()
    raise ValueError(f"unknown strategy: {name}")


def variants(bars, strategy_name: str, indicator_history=()):
    return {
        "base": strategy_signals(bars, base_strategy(strategy_name)),
        "rsi_14_aligned": confirmed_signals(bars, base_strategy(strategy_name), indicator_history=indicator_history, require_rsi=True),
        "macd_12_26_9_aligned": confirmed_signals(bars, base_strategy(strategy_name), indicator_history=indicator_history, require_macd=True),
        "rsi_and_macd_aligned": confirmed_signals(
            bars, base_strategy(strategy_name), indicator_history=indicator_history, require_rsi=True, require_macd=True,
        ),
    }


def select_training_variant(markouts: dict[str, list[dict[str, object]]], holdout_start: date) -> dict[str, object]:
    """Choose one version on early dates only, then reveal later dates."""
    summaries = {name: segmented_summary(rows, holdout_start) for name, rows in markouts.items()}
    eligible = [name for name in VARIANTS if int(summaries[name]["training"]["measured_signals"]) >= 15]
    if not eligible:
        return {"selected_variant": None, "reason": "too_few_training_signals", "summaries": summaries}
    winner = max(
        eligible,
        key=lambda name: (
            float(summaries[name]["training"]["average_return_pct"] or float("-inf")),
            int(summaries[name]["training"]["measured_signals"]),
            -VARIANTS.index(name),
        ),
    )
    later = summaries[winner]["holdout"]
    passed = int(later["measured_signals"]) >= 10 and float(later["average_return_pct"] or 0.0) > 0.0
    return {
        "selected_variant": winner,
        "selection_rule": "highest earlier-data average option return; ties use more signals then declared order",
        "later_data_gate": "at least 10 later signals and positive average return",
        "later_data_passed": passed,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--strategy", choices=("v2_orb_pullback", "trend_continuation"), required=True)
    parser.add_argument("--ticker", default="TSLA")
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--hold-minutes", type=int, default=90)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=.80)
    parser.add_argument("--max-premium", type=float, default=10.0)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    if not args.archive.is_file() or args.hold_minutes < 1:
        parser.error("an existing archive and positive hold are required")

    dataset, filenames = load_csv(args.bars), archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    markouts = {name: list(existing.get("markouts_by_variant", {}).get(name, [])) for name in VARIANTS}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Predeclared RSI/MACD confirmation comparison using paid TSLA option quotes; research-only.",
        "data_source": f"local paid portal archive: {args.archive}", "ticker": args.ticker.upper(),
        "strategy": args.strategy, "variants": list(VARIANTS), "holdout_start": args.holdout_start.isoformat(),
        "hold_minutes": args.hold_minutes, "max_signals_per_day": None,
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "candidate_files": len(filenames),
        "filter_definition": "Long: RSI >=50 and/or MACD histogram >0. Short: RSI <=50 and/or histogram <0.",
    }
    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        assert trading_day is not None
        day = day_bars(dataset, trading_day)
        # Give RSI/MACD the immediately preceding completed 60 bars (not
        # future bars).  The setup itself still receives ``day`` only, so its
        # opening range and per-day state remain unchanged.
        prior = tuple(bar for bar in dataset.bars if bar.timestamp < day[0].timestamp)[-60:] if day else ()
        labeled = variants(day, args.strategy, prior) if day else {name: () for name in VARIANTS}
        if not day:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
            completed.add(filename)
        elif not labeled["base"]:
            skipped.append({"filename": filename, "reason": "no_base_strategy_signal"})
            completed.add(filename)
        else:
            raw_path = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                result_sets = run_databento_cbbo_markouts_for_labeled_signals(
                    day, [raw_path], labeled, args.ticker, hold_minutes=args.hold_minutes,
                    min_dte=args.min_dte, max_dte=args.max_dte, min_premium=args.min_premium,
                    max_premium=args.max_premium, max_spread_pct=args.max_spread_pct,
                )
                for name, rows in result_sets.items():
                    markouts[name].extend(result_row(row) for row in rows)
                completed.add(filename)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)
        selection = select_training_variant(markouts, args.holdout_start)
        write_checkpoint(args.output, {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "markouts_by_variant": markouts, "selection": selection,
            "complete": len(completed) == len(filenames),
        })
        if len(completed) == len(filenames) or (args.progress_every and len(completed) % args.progress_every == 0):
            print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                              "selected_variant": selection["selected_variant"], "latest_file": filename}), flush=True)


if __name__ == "__main__":
    main()
