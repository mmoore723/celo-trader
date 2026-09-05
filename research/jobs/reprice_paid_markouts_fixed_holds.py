#!/usr/bin/env python3
"""Reprice frozen paid-option entries at several fixed exit clocks.

This is the fast path for an exit-only question.  It reuses the exact signal,
contract, and real entry ask from a completed paid-quote study, then scans each
relevant daily file once for the first real bid at every declared exit clock.
It does not rerun the strategy or contract selector and cannot place orders.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.option_markouts import _window_matcher
from research.engine.providers.databento import (
    _open_csv,
    _parse_symbol,
    _prices,
    _timestamp,
    convert_databento_dbn_file,
)
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, extract_archive_file, write_checkpoint,
)


def rows_at_path(payload: object, dotted_path: str) -> list[dict[str, object]]:
    """Read a reusable markout list without requiring one report schema."""
    value = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"input has no rows path {dotted_path!r}")
        value = value[part]
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"input rows path {dotted_path!r} must resolve to a list of objects")
    return value


def reprice_day(
    raw_path: Path,
    entries: list[dict[str, object]],
    holds: tuple[int, ...],
    *,
    ticker: str,
    max_wait: timedelta = timedelta(minutes=1),
) -> tuple[dict[int, list[dict[str, object]]], list[dict[str, object]]]:
    """Return same-contract bid markouts after one streaming file pass."""
    requests: list[tuple[int, int, datetime, datetime, str]] = []
    windows: list[tuple[datetime, datetime]] = []
    for index, row in enumerate(entries):
        entry_time = datetime.fromisoformat(str(row["entry_time"]))
        entry_bar_time = entry_time.replace(second=0, microsecond=0)
        contract = str(row["contract"])
        for hold in holds:
            target = entry_bar_time + timedelta(minutes=hold)
            deadline = target + max_wait
            requests.append((index, hold, target, deadline, contract))
            windows.append((target, deadline))
    in_window = _window_matcher(windows)
    found: dict[tuple[int, int], tuple[datetime, float]] = {}
    with _open_csv(raw_path) as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "symbol" not in reader.fieldnames:
            raise ValueError(f"{raw_path.name} is missing Databento symbol column")
        for raw in reader:
            try:
                timestamp = datetime.fromisoformat(_timestamp(raw))
            except ValueError:
                continue
            if not in_window(timestamp):
                continue
            identity, prices = _parse_symbol(raw.get("symbol"), ticker), _prices(raw)
            if identity is None or prices is None:
                continue
            option_symbol = identity[0]
            for index, hold, target, deadline, contract in requests:
                key = (index, hold)
                if key in found or option_symbol != contract:
                    continue
                if target <= timestamp <= deadline:
                    found[key] = (timestamp, prices[0])

    repriced = {hold: [] for hold in holds}
    missing: list[dict[str, object]] = []
    for index, row in enumerate(entries):
        for hold in holds:
            quote = found.get((index, hold))
            if quote is None:
                missing.append({
                    "signal_time": row["signal_time"], "contract": row["contract"],
                    "hold_minutes": hold, "reason": "no_executable_bid_in_one_minute_window",
                })
                continue
            timestamp, exit_bid = quote
            output = dict(row)
            output["ticker"] = ticker.upper()
            output["exit_time"] = timestamp.isoformat()
            output["exit_bid"] = exit_bid
            output["return_pct"] = round(
                (exit_bid - float(row["entry_ask"])) / float(row["entry_ask"]) * 100.0, 4,
            )
            output["underlying_exit"] = None
            repriced[hold].append(output)
    return repriced, missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--source-rule",
        default="fixed_30m",
        help="Rule under markouts_by_rule (legacy shorthand).",
    )
    source.add_argument(
        "--source-rows-path",
        help="Dotted path to frozen entry rows in any completed report.",
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--hold-minutes", type=int, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    args = parser.parse_args()
    holds = tuple(sorted(set(args.hold_minutes)))
    if not args.archive.exists() or not holds or any(hold < 1 for hold in holds):
        parser.error("an existing archive and positive hold minutes are required")
    source_report = json.loads(args.input.read_text(encoding="utf-8"))
    if not source_report.get("complete"):
        parser.error("input must be a complete paid study")
    rows_path = args.source_rows_path or f"markouts_by_rule.{args.source_rule}"
    try:
        entries = list(rows_at_path(source_report, rows_path))
    except ValueError as exc:
        parser.error(str(exc))
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in entries:
        grouped.setdefault(datetime.fromisoformat(str(row["signal_time"])).date().isoformat(), []).append(row)
    filenames = {
        day.isoformat(): filename
        for filename in archive_filenames(args.archive)
        if (day := batch_file_date(filename)) is not None
    }
    missing_days = sorted(set(grouped) - set(filenames))
    if missing_days:
        parser.error(f"archive is missing source-entry sessions: {', '.join(missing_days)}")

    existing = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    completed = set(existing.get("processed_dates", []))
    marks = {hold: list(existing.get("markouts_by_hold", {}).get(str(hold), [])) for hold in holds}
    missing = list(existing.get("missing_exit_quotes", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Exit-only fixed-hold repricing of frozen paid-option entries; research-only.",
        "source_study": str(args.input), "source_rows_path": rows_path,
        "ticker": args.ticker.upper(), "hold_minutes_tested": list(holds),
        "entry_invariant": "exact source signal, contract, entry timestamp, and real entry ask",
        "execution": "first real same-contract bid in the one-minute window at each exit clock",
        "reused_source_entries": len(entries), "candidate_dates": len(grouped),
    }
    for trading_day in sorted(grouped):
        if trading_day in completed:
            continue
        filename = filenames[trading_day]
        source_path = args.archive / filename if args.archive.is_dir() else None
        staged: Path | None = None
        decoded: Path | None = None
        try:
            staged = source_path or extract_archive_file(args.archive, filename, args.scratch_dir / filename)
            quote_path = staged
            if ".dbn" in filename.lower():
                decoded = args.scratch_dir / f"{Path(filename).name}.decoded.csv.zst"
                quote_path = convert_databento_dbn_file(staged, decoded)
            by_hold, missing_for_day = reprice_day(
                quote_path, grouped[trading_day], holds, ticker=args.ticker.upper(),
            )
            for hold, rows in by_hold.items():
                marks[hold].extend(rows)
            missing.extend(missing_for_day)
        finally:
            if decoded is not None:
                decoded.unlink(missing_ok=True)
            if staged is not None and source_path is None:
                staged.unlink(missing_ok=True)
        completed.add(trading_day)
        payload = {
            **base, "processed_dates": sorted(completed),
            "markouts_by_hold": {str(hold): marks[hold] for hold in holds},
            "missing_exit_quotes": missing,
            "complete": len(completed) == len(grouped),
        }
        write_checkpoint(args.output, payload)
        print(json.dumps({
            "processed": len(completed), "candidate_dates": len(grouped),
            "latest_date": trading_day,
        }), flush=True)


if __name__ == "__main__":
    main()
