#!/usr/bin/env python3
"""Compare causal exits for fixed one-minute ORB-retest entries.

The entry rule is fixed: first clean one-minute retouch after the 9:30-9:45
opening range. It can replay calls, puts, or both; it only changes the exit
decision. This script does not select entries, place orders, or alter the
paper bot. It compares actual ask-to-bid option quotes already present in the
local paid archive.
"""
from __future__ import annotations

import argparse
from datetime import date, time
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.exit_rules import planned_one_minute_dynamic_exits
from research.engine.models import Side
from research.engine.option_markouts import run_databento_cbbo_markouts_for_exit_plans
from research.engine.orb_retouch import one_minute_first_retouch_signals
from research.jobs.compare_paid_orb_exits import select_training_rule
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file, result_row, write_checkpoint,
)


def rules_for_cap(cap_minutes: int) -> tuple[str, ...]:
    suffix = f"_{cap_minutes}m"
    return (
        "fixed_90m" if cap_minutes == 90 else f"fixed{suffix}", f"structural_stop{suffix}",
        f"confirmed_vwap_ema{suffix}", f"hybrid_stop_vwap_ema{suffix}",
    )


def comparable_markouts(markouts_by_rule: dict[str, list[dict[str, object]]]) -> dict[str, list[dict[str, object]]]:
    """Keep only signals with a fill under every exit being compared.

    A dynamic exit can have an executable bid before a day ends when the
    90-minute cap does not.  Comparing its full row set with a shorter fixed
    cap row set would confound exit quality with quote availability.  The exit
    choice must therefore use the intersection of signal timestamps.
    """
    ids_by_rule = {
        rule: {str(row["signal_time"]) for row in rows}
        for rule, rows in markouts_by_rule.items()
    }
    common = set.intersection(*ids_by_rule.values()) if ids_by_rule else set()
    return {
        rule: [row for row in rows if str(row["signal_time"]) in common]
        for rule, rows in markouts_by_rule.items()
    }


class _FixedSignals:
    """Tiny strategy adapter so the executable quote engine replays fixed signals."""

    def __init__(self, signals):
        self._by_time = {signal.timestamp: signal for signal in signals}

    def evaluate(self, history):
        return self._by_time.get(history[-1].timestamp) if history else None


def _eligible_signals(bars, tolerance_pct: float, *, side: str, entry_deadline: time):
    """Return the predeclared entry universe; exits cannot alter it."""
    signals = one_minute_first_retouch_signals(
        bars, tolerance_pct=tolerance_pct, entry_deadline=entry_deadline,
    )
    if side == "calls":
        return tuple(signal for signal in signals if signal.side is Side.LONG)
    if side == "puts":
        return tuple(signal for signal in signals if signal.side is Side.SHORT)
    return signals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--ticker", default="TSLA")
    parser.add_argument("--side", choices=("calls", "puts", "both"), default="calls")
    parser.add_argument("--entry-deadline", type=time.fromisoformat, default=time(10, 30))
    parser.add_argument("--cap-minutes", type=int, default=90)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=.80)
    parser.add_argument("--max-premium", type=float, default=10.0)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument("--retest-tolerance-pct", type=float, default=.0005)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()
    if not (args.archive.is_file() or args.archive.is_dir()) or args.cap_minutes < 1:
        parser.error("archive ZIP or extracted batch folder must exist")

    dataset, filenames = load_csv(args.bars), archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    rules = rules_for_cap(args.cap_minutes)
    completed = set(existing.get("processed_files", []))
    raw = existing.get("markouts_by_rule", {})
    markouts = {rule: list(raw.get(rule, [])) for rule in rules}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Exit-only comparison for fixed one-minute ORB retouches; research-only.",
        "data_source": f"local paid portal archive: {args.archive}",
        "ticker": args.ticker.upper(), "strategy": "V2_ORB_PULLBACK_1M_RETOUCH_EXIT_COMPARISON",
        "fixed_entry": (
            "first clean post-breakout retouch; direction=" + args.side
            + "; signal time <= " + args.entry_deadline.strftime("%H:%M") + " ET"
        ),
        "execution": "entry at actual ask and same-contract exit at actual bid; no midpoint or synthetic option pricing",
        "exit_definitions": {
            rules[0]: f"{args.cap_minutes} minutes after entry",
            rules[1]: f"underlying loses the opening-range invalidation level; otherwise {args.cap_minutes} minutes",
            rules[2]: f"two completed 1m bars lose both VWAP and EMA(9); otherwise {args.cap_minutes} minutes",
            rules[3]: f"first structural stop or two-bar VWAP/EMA loss; otherwise {args.cap_minutes} minutes",
        },
        "causality": "one-minute close decisions are made one minute later; option exit uses first real bid after that decision",
        "holdout_start": args.holdout_start.isoformat(), "bars_path": str(args.bars),
        "bars_sha256": dataset.sha256, "candidate_files": len(filenames),
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte, "min_premium": args.min_premium,
                        "max_premium": args.max_premium, "max_spread_pct": args.max_spread_pct},
    }
    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        bars = day_bars(dataset, trading_day) if trading_day else ()
        signals = _eligible_signals(
            bars, args.retest_tolerance_pct, side=args.side,
            entry_deadline=args.entry_deadline,
        ) if bars else ()
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
        elif not signals:
            skipped.append({"filename": filename, "reason": "no_eligible_fixed_retouch"})
        else:
            plans = {rule: {} for rule in rules}
            for signal in signals:
                entry = next((bar for bar in bars if bar.timestamp > signal.timestamp), None)
                if entry:
                    for rule, plan in planned_one_minute_dynamic_exits(
                        bars, signal, entry, cap_minutes=args.cap_minutes,
                    ).items():
                        plans[rule][signal.timestamp] = plan
            raw_path = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                results = run_databento_cbbo_markouts_for_exit_plans(
                    bars, [raw_path], _FixedSignals(signals), args.ticker, plans,
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
        selection = select_training_rule(comparable, args.holdout_start, rules=rules)
        write_checkpoint(args.output, {**base, "processed_files": sorted(completed), "skipped_files": skipped,
                                       "markouts_by_rule": markouts,
                                       "comparable_markouts_by_rule": comparable,
                                       "comparison_universe": "only signal timestamps with executable fills for every predeclared exit",
                                       "selection": selection,
                                       "complete": len(completed) == len(filenames)})
        if len(completed) == len(filenames) or len(completed) % args.progress_every == 0:
            print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                              "selected_exit_rule": selection["selected_exit_rule"], "latest_file": filename}), flush=True)


if __name__ == "__main__":
    main()
