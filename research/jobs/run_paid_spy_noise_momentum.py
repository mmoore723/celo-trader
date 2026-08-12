#!/usr/bin/env python3
"""Test predeclared SPY noise-boundary momentum with paid option quotes.

This runner does not touch the bot or request any additional data.  It uses
the locally delivered OPRA CBBO files: an option is bought at its real ask and
the exact same contract is sold at its real bid.  It compares the source
strategy's three predeclared exits on identical SPY entries:

* fixed pre-close;
* current adaptive noise boundary;
* current adaptive boundary combined with VWAP.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.exit_rules import planned_noise_momentum_exits
from research.engine.noise_momentum import boundaries_by_timestamp, noise_momentum_signals
from research.engine.option_markouts import run_databento_cbbo_markouts_for_exit_plans
from research.jobs.compare_paid_one_minute_orb_call_exits import comparable_markouts
from research.jobs.compare_paid_orb_exits import select_training_rule
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file,
    result_row, write_checkpoint,
)


RULES = ("fixed_preclose", "current_band", "current_band_vwap")


class _FixedSignals:
    """Adapt one day of already-generated signals to the quote executor."""

    def __init__(self, signals):
        self._by_time = {signal.timestamp: signal for signal in signals}

    def evaluate(self, history):
        return self._by_time.get(history[-1].timestamp) if history else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=.80)
    parser.add_argument("--max-premium", type=float, default=10.0)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument("--progress-every", type=int, default=5)
    args = parser.parse_args()
    if not (args.archive.is_file() or args.archive.is_dir()):
        parser.error("existing paid archive ZIP or extracted folder is required")

    dataset, filenames = load_csv(args.bars), archive_filenames(args.archive)
    all_signals = noise_momentum_signals(dataset.bars)
    all_boundaries = boundaries_by_timestamp(dataset.bars)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    raw = existing.get("markouts_by_rule", {})
    markouts = {rule: list(raw.get(rule, [])) for rule in RULES}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Predeclared SPY 14-session noise-boundary momentum test with locally paid option quotes; research-only.",
        "data_source": f"local paid portal archive: {args.archive}", "ticker": "SPY",
        "strategy": "V2_SPY_NOISE_MOMENTUM",
        "entry": "completed 1-minute close outside the 14-session time-of-day adaptive noise zone at :00/:30, 10:00-15:30; fill on next minute",
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option pricing",
        "exit_definitions": {
            "fixed_preclose": "hold until 15:59 ET",
            "current_band": "exit after a completed half-hour check closes back through the current adaptive boundary; otherwise 15:59",
            "current_band_vwap": "exit after a completed half-hour check loses the protective current boundary or VWAP; otherwise 15:59",
        },
        "causality": "boundary uses only the prior 14 sessions; a completed-bar decision exits from the next minute's real option bid",
        "holdout_start": args.holdout_start.isoformat(), "bars_path": str(args.bars),
        "bars_sha256": dataset.sha256, "candidate_files": len(filenames),
        "underlying_signals_before_option_eligibility": len(all_signals),
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte, "min_premium": args.min_premium,
                        "max_premium": args.max_premium, "max_spread_pct": args.max_spread_pct},
    }
    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        bars = day_bars(dataset, trading_day) if trading_day else ()
        signals = tuple(signal for signal in all_signals if signal.timestamp.date() == trading_day)
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
        elif not signals:
            skipped.append({"filename": filename, "reason": "no_noise_boundary_transition"})
        else:
            plans = {rule: {} for rule in RULES}
            for signal in signals:
                entry = next((bar for bar in bars if bar.timestamp > signal.timestamp), None)
                if entry:
                    for rule, plan in planned_noise_momentum_exits(
                        bars, signal, entry, boundaries=all_boundaries,
                    ).items():
                        plans[rule][signal.timestamp] = plan
            raw_path = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                results = run_databento_cbbo_markouts_for_exit_plans(
                    bars, [raw_path], _FixedSignals(signals), "SPY", plans,
                    min_dte=args.min_dte, max_dte=args.max_dte, min_premium=args.min_premium,
                    max_premium=args.max_premium, max_spread_pct=args.max_spread_pct,
                )
                for rule, rows in results.items():
                    markouts[rule].extend(result_row(row) for row in rows)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)
        completed.add(filename)
        comparable = comparable_markouts(markouts)
        selection = select_training_rule(comparable, args.holdout_start, rules=RULES)
        write_checkpoint(args.output, {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "markouts_by_rule": markouts, "comparable_markouts_by_rule": comparable,
            "comparison_universe": "only signals with an executable fill under every predeclared exit",
            "selection": selection, "complete": len(completed) == len(filenames),
        })
        if len(completed) == len(filenames) or len(completed) % args.progress_every == 0:
            print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                              "selected_exit_rule": selection["selected_exit_rule"], "latest_file": filename}), flush=True)


if __name__ == "__main__":
    main()
