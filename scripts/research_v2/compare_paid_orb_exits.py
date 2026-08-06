#!/usr/bin/env python3
"""Compare fixed, VWAP, and EMA exits on the already-paid TSLA quotes.

The strategy, contract-selection rules, and data split are fixed before this
run.  The script makes no production, broker, or configuration changes.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import load_csv
from research_v2.exit_rules import planned_exits
from research_v2.option_markouts import (
    run_databento_cbbo_markouts_for_exit_plans, strategy_signals,
)
from scripts.research_v2.run_paid_databento_job import (
    archive_filenames, batch_file_date, build_strategy, day_bars,
    extract_archive_file, result_row, summarize, write_checkpoint,
)
from scripts.research_v2.tune_paid_orb_holds import segmented_summary


RULES = ("fixed_90m", "vwap_loss_90m", "ema9_loss_90m", "vwap_or_ema9_90m")


def select_training_rule(
    markouts_by_rule: dict[str, list[dict[str, object]]], holdout_start: date,
    minimum_training_signals: int = 15,
) -> dict[str, object]:
    """Pick a rule from earlier data only, then disclose its later result."""
    summaries = {rule: segmented_summary(rows, holdout_start) for rule, rows in markouts_by_rule.items()}
    eligible = [
        rule for rule in RULES
        if int(summaries[rule]["training"]["measured_signals"]) >= minimum_training_signals
    ]
    if not eligible:
        return {"selected_exit_rule": None, "reason": "too_few_training_signals", "summaries": summaries}
    winner = max(
        eligible,
        key=lambda rule: (
            float(summaries[rule]["training"]["average_return_pct"] or float("-inf")),
            int(summaries[rule]["training"]["measured_signals"]),
            -RULES.index(rule),
        ),
    )
    holdout = summaries[winner]["holdout"]
    passes = (int(holdout["measured_signals"]) >= 10
              and float(holdout["average_return_pct"] or 0.0) > 0.0)
    return {
        "selected_exit_rule": winner,
        "selection_rule": "highest average return on training only; ties use more signals then earlier predeclared rule",
        "holdout_gate": "at least 10 holdout signals and positive average return",
        "holdout_passed": passes,
        "summaries": summaries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare predeclared V2 ORB exits using paid executable quotes")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--ticker", default="TSLA")
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 3, 1))
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=0.08)
    parser.add_argument("--progress-every", type=int, default=25,
                        help="Checkpoint every day but print progress only every N days (0 = final only)")
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error(f"archive does not exist: {args.archive}")

    dataset = load_csv(args.bars)
    filenames = archive_filenames(args.archive)
    if not filenames:
        raise RuntimeError("archive contains no daily CBBO files")
    existing: dict[str, object] = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    raw_markouts = existing.get("markouts_by_rule", {})
    markouts_by_rule = {rule: list(raw_markouts.get(rule, [])) for rule in RULES}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)

    base = {
        "purpose": "Predeclared V2 TSLA ORB pullback VWAP/EMA exit comparison; research-only, never a broker command.",
        "data_source": f"local paid portal archive: {args.archive}",
        "ticker": args.ticker.upper(), "strategy": "orb_pullback",
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "exit_definitions": {
            "fixed_90m": "exit at 90 minutes after entry bar",
            "vwap_loss_90m": "on a later completed five-minute bar, long close <= session VWAP or short close >= session VWAP; otherwise 90-minute cap",
            "ema9_loss_90m": "on a later completed five-minute bar, long close <= session EMA(9) or short close >= session EMA(9); otherwise 90-minute cap",
            "vwap_or_ema9_90m": "first completed-bar VWAP or EMA(9) loss; otherwise 90-minute cap",
        },
        "causality": "A bar-close exit decision is not sent until five minutes after that bar's opening timestamp.",
        "bars_path": str(args.bars), "bars_sha256": dataset.sha256,
        "holdout_start": args.holdout_start.isoformat(),
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
        strategy = build_strategy("orb_pullback")
        signals = strategy_signals(bars, strategy) if bars else ()
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
            completed.add(filename)
        elif not signals:
            skipped.append({"filename": filename, "reason": "no_strategy_signal"})
            completed.add(filename)
        else:
            plans_by_rule = {rule: {} for rule in RULES}
            for signal in signals:
                entry_bar = next((bar for bar in bars if bar.timestamp > signal.timestamp), None)
                if entry_bar is None:
                    continue
                for rule, plan in planned_exits(bars, signal, entry_bar).items():
                    plans_by_rule[rule][signal.timestamp] = plan
            raw_path: Path | None = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                # OpeningRangePullback is intentionally stateful while it
                # emits at most one signal per day.  The markout engine must
                # receive a fresh instance so it can regenerate the same
                # causal signal rather than inheriting the planning pass.
                results = run_databento_cbbo_markouts_for_exit_plans(
                    bars, [raw_path], build_strategy("orb_pullback"), args.ticker, plans_by_rule,
                    min_dte=args.min_dte, max_dte=args.max_dte,
                    min_premium=args.min_premium, max_premium=args.max_premium,
                    max_spread_pct=args.max_spread_pct,
                )
                for rule, rows in results.items():
                    markouts_by_rule[rule].extend(result_row(row) for row in rows)
                completed.add(filename)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)

        selection = select_training_rule(markouts_by_rule, args.holdout_start)
        write_checkpoint(args.output, {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "markouts_by_rule": markouts_by_rule, "selection": selection,
            "complete": len(completed) == len(filenames),
        })
        processed = len(completed)
        if (args.progress_every and processed % args.progress_every == 0) or processed == len(filenames):
            print(json.dumps({"processed": processed, "candidate_files": len(filenames),
                              "selected_exit_rule": selection["selected_exit_rule"],
                              "latest_file": filename}, indent=2), flush=True)


if __name__ == "__main__":
    main()
