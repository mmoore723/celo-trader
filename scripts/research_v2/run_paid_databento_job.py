#!/usr/bin/env python3
"""Evaluate an existing Databento batch job one file at a time.

This is deliberately a *research-only* command.  It retrieves files that
were already purchased, evaluates each day from real option quotes, then
deletes the temporary raw file.  It never creates a Databento request and it
never talks to a broker.

The initial strategy is the confirmed Opening Range Breakout (ORB).  The
purpose is to find out whether that underlying setup has any executable TSLA
option edge when entries pay the ask and exits receive the bid.  A negative
result rejects ORB; it must not be "tuned" into production by looking at the
same result repeatedly.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research_v2.data import BarDataset, load_csv
from research_v2.option_markouts import OptionMarkout, run_databento_cbbo_markouts
from research_v2.strategies import OpeningRangeBreakout, OpeningRangeBreakoutConfig


_FILE_DATE = re.compile(r"-(\d{8})\.cbbo-1m\.csv(?:\.zst)?$")


def batch_file_date(filename: str) -> date | None:
    """Return the trading date embedded in a Databento daily CBBO filename."""
    match = _FILE_DATE.search(filename)
    return date.fromisoformat(
        f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:]}"
    ) if match else None


def day_bars(dataset: BarDataset, trading_day: date):
    """Return the frozen underlying bars for exactly one calendar session."""
    return tuple(bar for bar in dataset.bars if bar.timestamp.date() == trading_day)


def result_row(result: OptionMarkout) -> dict[str, object]:
    return {
        "signal_time": result.signal_time.isoformat(),
        "entry_time": result.entry_time.isoformat(),
        "exit_time": result.exit_time.isoformat(),
        "side": result.side.value,
        "contract": result.contract_symbol,
        "entry_ask": result.entry_ask,
        "exit_bid": result.exit_bid,
        "return_pct": result.return_pct,
        "underlying_entry": result.underlying_entry,
        "underlying_exit": result.underlying_exit,
    }


def write_checkpoint(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def summarize(markouts: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = tuple(markouts)
    returns = [float(row["return_pct"]) for row in rows]
    return {
        "measured_signals": len(rows),
        "positive_markouts": sum(value > 0 for value in returns),
        "win_rate_pct": round(sum(value > 0 for value in returns) / len(returns) * 100, 2) if returns else None,
        "average_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "total_return_pct": round(sum(returns), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream an already-paid daily Databento CBBO batch job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--bars", type=Path, required=True, help="Frozen regular-session underlying bars CSV")
    parser.add_argument("--output", type=Path, required=True, help="Resumable JSON result file")
    parser.add_argument("--scratch-dir", type=Path, required=True, help="Small temporary download directory")
    parser.add_argument("--hold-minutes", type=int, default=60)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=0.08)
    parser.add_argument("--limit-days", type=int, default=0, help="Optional safe cap for a trial run")
    args = parser.parse_args()

    if args.hold_minutes < 1 or args.limit_days < 0:
        parser.error("hold-minutes must be positive and limit-days cannot be negative")
    if not (0 <= args.min_dte <= args.max_dte and 0 <= args.min_premium <= args.max_premium):
        parser.error("invalid option eligibility limits")

    # Import only at execution time: unit tests and all non-Databento research
    # remain usable without a paid-data credential.
    import databento as db

    dataset = load_csv(args.bars)
    existing: dict[str, object] = {}
    if args.output.exists():
        existing = json.loads(args.output.read_text(encoding="utf-8"))
    completed = set(existing.get("processed_files", []))
    markouts = list(existing.get("markouts", []))
    skipped = list(existing.get("skipped_files", []))

    client = db.Historical()
    files = client.batch.list_files(args.job_id)
    filenames = sorted(
        item["filename"] for item in files
        if isinstance(item.get("filename"), str) and batch_file_date(item["filename"]) is not None
    )
    if args.limit_days:
        filenames = filenames[:args.limit_days]

    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Paid TSLA option quote-to-quote ORB screen; research-only, never a broker command.",
        "job_id": args.job_id,
        "ticker": args.ticker.upper(),
        "strategy": "confirmed_opening_range_breakout",
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "bars_path": str(args.bars),
        "bars_sha256": dataset.sha256,
        "hold_minutes": args.hold_minutes,
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
                downloaded = client.batch.download(
                    args.job_id, output_dir=args.scratch_dir, filename_to_download=filename,
                )
                if len(downloaded) != 1:
                    raise RuntimeError(f"expected one downloaded file, received {len(downloaded)}")
                raw_path = downloaded[0]
                strategy = OpeningRangeBreakout(OpeningRangeBreakoutConfig())
                results = run_databento_cbbo_markouts(
                    bars, [raw_path], strategy, underlying=args.ticker,
                    hold_minutes=args.hold_minutes, min_dte=args.min_dte, max_dte=args.max_dte,
                    min_premium=args.min_premium, max_premium=args.max_premium,
                    max_spread_pct=args.max_spread_pct,
                )
                markouts.extend(result_row(result) for result in results)
                completed.add(filename)
            finally:
                # A full job does not fit on the small EC2 disk.  Results are
                # checkpointed below; only this day's temporary download is removed.
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)

        payload: dict[str, object] = {
            **base,
            "processed_files": sorted(completed),
            "skipped_files": skipped,
            "markouts": markouts,
            "summary": summarize(markouts),
            "complete": len(completed) == len(filenames),
        }
        write_checkpoint(args.output, payload)
        print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                          "summary": payload["summary"], "latest_file": filename}, indent=2), flush=True)

    # Remove the job subdirectory Databento creates if it is now empty.
    job_dir = args.scratch_dir / args.job_id
    if job_dir.exists() and not any(job_dir.iterdir()):
        shutil.rmtree(job_dir)


if __name__ == "__main__":
    main()
