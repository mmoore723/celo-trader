#!/usr/bin/env python3
"""Evaluate a conservative one-minute ORB retouch proxy with paid CBBO quotes.

This is not a tick-for-tick replay of the deployed immediate-quote entry.
The first 15 one-minute bars define the range; a completed later minute closes
outside it; a later completed minute cleanly retouches the broken boundary.
Because frozen underlying OHLC bars do not reveal the order of events inside
that retouch minute, the option fill is taken from the following minute.
It pays the actual option ask and receives the actual option bid, never places
orders, and never requests paid data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.option_markouts import run_databento_cbbo_markouts_for_labeled_signals
from research.engine.orb_retouch import one_minute_first_retouch_signals
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file, result_row, summarize, write_checkpoint,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--hold-minutes", type=int, default=90)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument("--retest-tolerance-pct", type=float, default=.0005)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()
    # Databento portal deliveries may be kept as the original ZIP or as the
    # extracted folder of daily CBBO files.  Both are the same already-paid,
    # immutable input; accepting both avoids a pointless re-zip before local
    # research.
    if not args.archive.exists() or not (args.archive.is_file() or args.archive.is_dir()) or args.hold_minutes < 1:
        parser.error("an existing archive ZIP/folder and positive hold-minutes are required")

    dataset, filenames = load_csv(args.bars), archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    markouts = list(existing.get("markouts", []))
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Conservative completed-one-minute confirmation proxy of the deployed ORB breakout-to-first-retest entry using paid option quotes; research-only.",
        "data_source": f"local paid portal archive: {args.archive}", "ticker": args.ticker.upper(),
        "strategy": "V2_ORB_PULLBACK_1M_RETOUCH_PROXY",
        "entry_model": "completed_1m_breakout_then_clean_1m_retouch_then_next_minute_option_quote_proxy",
        "important_limit": "Underlying OHLC minutes cannot prove tick order inside a minute. A minute crossing through the retest level is rejected rather than treated as an entry; the paid option fill starts in the following minute, not at the exact live retouch.",
        "execution": "option entry at actual ask from the minute after confirmation; same-contract exit at actual bid; no midpoint or synthetic option price",
        "bars_path": str(args.bars), "bars_sha256": dataset.sha256, "hold_minutes": args.hold_minutes,
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte, "min_premium": args.min_premium,
                        "max_premium": args.max_premium, "max_spread_pct": args.max_spread_pct},
        "retest_tolerance_pct": args.retest_tolerance_pct, "candidate_files": len(filenames),
    }
    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        assert trading_day is not None
        bars = day_bars(dataset, trading_day)
        signals = one_minute_first_retouch_signals(bars, tolerance_pct=args.retest_tolerance_pct) if bars else ()
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
        elif not signals:
            skipped.append({"filename": filename, "reason": "no_clean_one_minute_retouch"})
        else:
            raw_path = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                rows = run_databento_cbbo_markouts_for_labeled_signals(
                    bars, [raw_path], {"one_minute_retouch": signals}, args.ticker,
                    hold_minutes=args.hold_minutes, min_dte=args.min_dte, max_dte=args.max_dte,
                    min_premium=args.min_premium, max_premium=args.max_premium,
                    max_spread_pct=args.max_spread_pct,
                )["one_minute_retouch"]
                markouts.extend(result_row(row) for row in rows)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)
        completed.add(filename)
        payload = {**base, "processed_files": sorted(completed), "skipped_files": skipped,
                   "markouts": markouts, "summary": summarize(markouts),
                   "complete": len(completed) == len(filenames)}
        write_checkpoint(args.output, payload)
        if len(completed) == len(filenames) or len(completed) % args.progress_every == 0:
            print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                              "summary": payload["summary"], "latest_file": filename}), flush=True)


if __name__ == "__main__":
    main()
