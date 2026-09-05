#!/usr/bin/env python3
"""Evaluate an existing Databento batch job one file at a time.

This is deliberately a *research-only* command.  It retrieves files that
were already purchased, evaluates each day from real option quotes, then
deletes the temporary raw file.  It never creates a Databento request and it
never talks to a broker.

Each strategy is a pre-defined, causal TSLA hypothesis. The purpose is to
find out whether its underlying setup has any executable option edge when
entries pay the ask and exits receive the bid. A negative result rejects that
strategy; it must not be "tuned" into production by looking at the same
result repeatedly.
"""
from __future__ import annotations

import argparse
from datetime import date, time
from ftplib import FTP
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable
from zipfile import ZipFile


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import Bar, BarDataset, load_csv, resample_regular_session
from research.engine.option_markouts import OptionMarkout, run_databento_cbbo_markouts
from research.engine.strategies import (
    OpeningRangeBreakout, OpeningRangeBreakoutConfig,
    OpeningRangePullback, OpeningRangePullbackConfig,
    TrendContinuation, TrendContinuationConfig,
    AfternoonReversal, AfternoonReversalConfig,
    VWAPPullback, VWAPPullbackConfig,
    MiddayBreakdown, MiddayBreakdownConfig,
    ORBRsiMacdShort, ORBRsiMacdShortConfig,
    GapFillRTH, GapFillRTHConfig,
    FairValueGap, FairValueGapConfig,
    TurtleSoupRTH, TurtleSoupRTHConfig,
    EMAPullbackRTH, EMAPullbackRTHConfig,
)


_FILE_DATE = re.compile(r"-(\d{8})\.cbbo-1m\.(?:csv|dbn)(?:\.zst)?$")
_FTP_HOST = "ftp.databento.com"


def batch_file_date(filename: str) -> date | None:
    """Return the trading date embedded in a Databento daily CBBO filename."""
    match = _FILE_DATE.search(filename)
    return date.fromisoformat(
        f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:]}"
    ) if match else None


def manifest_filenames(payload: object) -> tuple[str, ...]:
    """Extract only daily CBBO data files from either manifest shape."""
    entries = payload.get("files", []) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("Databento manifest has no file list")
    names = [entry.get("filename") if isinstance(entry, dict) else entry for entry in entries]
    return tuple(sorted(
        name for name in names
        if isinstance(name, str) and batch_file_date(name) is not None
    ))


def archive_filenames(archive_path: Path) -> tuple[str, ...]:
    """List daily CBBO files from a portal ZIP or an extracted batch folder.

    Both are immutable deliveries of an already-paid batch. Supporting the
    extracted format lets a user use the portal's ordinary ``Download all``
    workflow without another large download or a manual repack step.
    """
    if archive_path.is_dir():
        return tuple(sorted(
            path.name for path in archive_path.iterdir()
            if path.is_file() and batch_file_date(path.name) is not None
        ))
    with ZipFile(archive_path) as archive:
        return tuple(sorted(
            name for name in archive.namelist()
            if batch_file_date(name) is not None
        ))


def extract_archive_file(archive_path: Path, filename: str, output_path: Path) -> Path:
    """Stage one daily file, never mutate or unpack the whole delivery.

    An extracted delivery is copied into scratch because callers delete the
    staged file after their day-level scan. Returning the source directly
    would silently delete a user's paid archive.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.is_dir():
        source = archive_path / filename
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copyfile(source, output_path)
        return output_path
    with ZipFile(archive_path) as archive, archive.open(filename) as source, output_path.open("wb") as target:
        shutil.copyfileobj(source, target, length=1_048_576)
    return output_path


def ftp_download(
    api_key: str, user_id: str, job_id: str, filename: str, output_path: Path,
) -> Path:
    """Download one existing batch file through Databento FTP.

    This is delivery of an already-paid batch object—not a historical streaming
    request.  The caller owns cleanup of ``output_path`` after it has been
    analyzed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    remote = f"/{user_id}/{job_id}/{filename}"
    with FTP(_FTP_HOST, timeout=120) as ftp:
        ftp.login(user=api_key, passwd="")
        with output_path.open("wb") as handle:
            ftp.retrbinary(f"RETR {remote}", handle.write, blocksize=1_048_576)
    return output_path


def day_bars(dataset: BarDataset, trading_day: date):
    """Return the frozen underlying bars for exactly one calendar session."""
    return tuple(bar for bar in dataset.bars if bar.timestamp.date() == trading_day)


def day_bars_with_prior_close(dataset: BarDataset, trading_day: date):
    """Provide one prior close as context for an opening-gap strategy.

    A gap is defined against yesterday's final regular-session close.  The
    paid CBBO file still supplies quotes only for ``trading_day``; this extra
    bar is underlying context, not a look-ahead quote or an additional trade.
    """
    today = day_bars(dataset, trading_day)
    if not today:
        return today
    prior = next((bar for bar in reversed(dataset.bars)
                  if bar.timestamp < today[0].timestamp), None)
    return (prior, *today) if prior is not None else today


def day_bars_with_regular_history(dataset: BarDataset, trading_day: date, history_bars: int = 100) -> tuple[Bar, ...]:
    """Give indicator strategies a bounded past while retaining today's full session.

    The signals are still emitted only on the current day's completed bars;
    earlier bars merely warm RSI/MACD, as on a normal continuous chart.
    """
    today = day_bars(dataset, trading_day)
    prior = tuple(bar for bar in dataset.bars if bar.timestamp < today[0].timestamp)[-history_bars:]
    return (*prior, *today) if today else today


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


def build_strategy(strategy_name: str, active_date: date | None = None):
    """Return one pre-defined, causal hypothesis; never tune during a run."""
    if strategy_name == "orb_breakout":
        return OpeningRangeBreakout(OpeningRangeBreakoutConfig())
    if strategy_name == "spy_narrow_orb_breakout":
        # Exploratory SPY screen: this cap was observed while reviewing the
        # paid period.  Keep it fixed for this option scan, but do not label
        # the result an independent holdout confirmation; a fresh period is
        # required before any promotion decision.
        return OpeningRangeBreakout(OpeningRangeBreakoutConfig(
            min_range_pct=0.0005, max_range_pct=0.0025,
        ))
    if strategy_name == "spy_narrow_orb_early_short":
        # Follow-up SPY hypothesis selected from the completed diagnostic:
        # only bearish, VWAP-aligned narrow-range breaks that occur before
        # 10:00 ET.  This remains research-only; its exit hold is chosen on
        # the earlier segment and judged on the later segment separately.
        return OpeningRangeBreakout(OpeningRangeBreakoutConfig(
            min_range_pct=0.0005, max_range_pct=0.0025,
            entry_deadline=time(10, 0), allow_long=False,
        ))
    if strategy_name == "spy_orb_rsi_macd_short":
        return ORBRsiMacdShort(ORBRsiMacdShortConfig(active_date=active_date))
    if strategy_name == "orb_pullback":
        return OpeningRangePullback(OpeningRangePullbackConfig())
    if strategy_name == "v2_orb_pullback":
        # This is the exact 0.05% retest rule selected before the later
        # paid-data holdout.  Keep it separate from the legacy/default ORB
        # pullback so a small-account contract study cannot accidentally test
        # a different entry rule than the V2 paper pilot.
        return OpeningRangePullback(OpeningRangePullbackConfig(retest_tolerance_pct=0.0005))
    if strategy_name == "vwap_pullback":
        return VWAPPullback(VWAPPullbackConfig())
    if strategy_name == "trend_continuation":
        return TrendContinuation(TrendContinuationConfig())
    if strategy_name == "afternoon_reversal":
        return AfternoonReversal(AfternoonReversalConfig())
    if strategy_name == "midday_breakdown":
        return MiddayBreakdown(MiddayBreakdownConfig())
    if strategy_name == "gap_fill_rth":
        # A real gap must reclaim the prior close on a completed 5-minute bar.
        # This keeps the continuation/reversal decision causal and distinct
        # from the opening-range strategies.
        return GapFillRTH(GapFillRTHConfig())
    if strategy_name == "fair_value_gap_rth":
        # The imbalance/retest rule is defined on completed five-minute
        # candles.  The paid quote runner enters only after the next complete
        # five-minute bar, never inside the candle that created the signal.
        return FairValueGap(FairValueGapConfig())
    if strategy_name == "turtle_soup_rth":
        # One failed 20-bar sweep followed by a confirming bar.  This is the
        # precise, testable version of the liquidity-sweep hypothesis.
        return TurtleSoupRTH(TurtleSoupRTHConfig())
    if strategy_name == "ema_pullback_rth":
        # Completed-bar three-EMA pullback/re-cross. This is research-only
        # until the real option ask-to-bid result demonstrates an edge.
        return EMAPullbackRTH(EMAPullbackRTHConfig())
    raise ValueError(f"unknown strategy: {strategy_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate an already-paid daily Databento CBBO batch job")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--job-id", help="Existing Databento job ID; retrieves one day at a time through FTP")
    source.add_argument("--archive", type=Path, help="Portal Download all ZIP; reads one day at a time locally")
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--strategy",
        choices=(
            "orb_breakout", "spy_narrow_orb_breakout", "spy_narrow_orb_early_short", "spy_orb_rsi_macd_short",
            "orb_pullback", "v2_orb_pullback", "vwap_pullback",
            "trend_continuation", "afternoon_reversal",
            "midday_breakdown", "gap_fill_rth", "turtle_soup_rth",
            "ema_pullback_rth", "fair_value_gap_rth",
        ),
        default="orb_breakout",
    )
    parser.add_argument("--bars", type=Path, required=True, help="Frozen regular-session underlying bars CSV")
    parser.add_argument("--output", type=Path, required=True, help="Resumable JSON result file")
    parser.add_argument("--scratch-dir", type=Path, required=True, help="Small temporary download directory")
    parser.add_argument("--hold-minutes", type=int, default=60)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=0.80)
    parser.add_argument("--max-premium", type=float, default=10.00)
    parser.add_argument("--max-spread-pct", type=float, default=0.08)
    parser.add_argument(
        "--max-signals-per-day", type=int, default=0,
        help="Use only the earliest N completed-bar signals each day (0 = no cap)",
    )
    parser.add_argument("--limit-days", type=int, default=0, help="Optional safe cap for a trial run")
    parser.add_argument(
        "--include-dates", type=Path,
        help="Optional newline-delimited YYYY-MM-DD list; process only those paid sessions.",
    )
    args = parser.parse_args()

    if args.hold_minutes < 1 or args.limit_days < 0 or args.max_signals_per_day < 0:
        parser.error("hold-minutes must be positive and day/signal limits cannot be negative")
    if not (0 <= args.min_dte <= args.max_dte and 0 <= args.min_premium <= args.max_premium):
        parser.error("invalid option eligibility limits")

    dataset = load_csv(args.bars)
    existing: dict[str, object] = {}
    if args.output.exists():
        existing = json.loads(args.output.read_text(encoding="utf-8"))
    completed = set(existing.get("processed_files", []))
    markouts = list(existing.get("markouts", []))
    skipped = list(existing.get("skipped_files", []))

    client = None
    user_id = ""
    if args.archive:
        # The portal delivery can be either the original ZIP or an extracted
        # folder of daily files.  Both are immutable local copies of the same
        # already-purchased batch, so accept either representation here.
        if not args.archive.exists() or not (args.archive.is_file() or args.archive.is_dir()):
            parser.error(f"archive does not exist: {args.archive}")
        filenames = archive_filenames(args.archive)
        source_description = f"local paid portal archive: {args.archive}"
    else:
        # Import only for FTP delivery: local archive analysis needs neither a
        # Databento credential nor network access.
        import databento as db
        client = db.Historical()
        # ``batch.list_files`` can time out for this 254-file package.  Job
        # details provide the FTP user ID; the tiny manifest has file names.
        details = client.batch.get_job_details(args.job_id)
        user_id = str(details.get("user_id") or "").strip()
        if not user_id:
            raise RuntimeError("Databento job details did not include its FTP user ID")
        manifest_path = args.scratch_dir / f"{args.job_id}-manifest.json"
        ftp_download(client.key, user_id, args.job_id, "manifest.json", manifest_path)
        filenames = manifest_filenames(json.loads(manifest_path.read_text(encoding="utf-8")))
        source_description = f"Databento FTP job: {args.job_id}"
    if not filenames:
        raise RuntimeError("Databento manifest contains no daily CBBO files")
    if args.limit_days:
        filenames = filenames[:args.limit_days]
    if args.include_dates:
        wanted = {
            text.strip() for text in args.include_dates.read_text(encoding="utf-8").splitlines()
            if text.strip() and not text.lstrip().startswith("#")
        }
        invalid = sorted(value for value in wanted if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
        if invalid:
            parser.error(f"include-dates contains invalid dates: {', '.join(invalid[:3])}")
        filenames = tuple(
            filename for filename in filenames
            if (trading_day := batch_file_date(filename)) is not None and trading_day.isoformat() in wanted
        )
        if not filenames:
            parser.error("include-dates selected no files from this archive")

    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Paid TSLA option quote-to-quote ORB screen; research-only, never a broker command.",
        "job_id": args.job_id,
        "data_source": source_description,
        "ticker": args.ticker.upper(),
        "strategy": args.strategy,
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "bars_path": str(args.bars),
        "bars_sha256": dataset.sha256,
        "hold_minutes": args.hold_minutes,
        "max_signals_per_day": args.max_signals_per_day or None,
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte,
                        "min_premium": args.min_premium, "max_premium": args.max_premium,
                        "max_spread_pct": args.max_spread_pct},
        "candidate_files": len(filenames),
        "included_dates_file": str(args.include_dates) if args.include_dates else None,
    }

    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        assert trading_day is not None
        bars = (day_bars_with_prior_close(dataset, trading_day)
                if args.strategy == "gap_fill_rth" else
                day_bars_with_regular_history(dataset, trading_day)
                if args.strategy == "spy_orb_rsi_macd_short" else
                day_bars(dataset, trading_day))
        if not bars:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
            completed.add(filename)
        else:
            raw_path: Path | None = None
            try:
                destination = args.scratch_dir / filename
                if args.archive:
                    raw_path = extract_archive_file(args.archive, filename, destination)
                else:
                    assert client is not None
                    raw_path = ftp_download(client.key, user_id, args.job_id, filename, destination)
                strategy = build_strategy(args.strategy, active_date=trading_day)
                results = run_databento_cbbo_markouts(
                    bars, [raw_path], strategy, underlying=args.ticker,
                    hold_minutes=args.hold_minutes, min_dte=args.min_dte, max_dte=args.max_dte,
                    min_premium=args.min_premium, max_premium=args.max_premium,
                    max_spread_pct=args.max_spread_pct,
                    max_signals=args.max_signals_per_day or None,
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

    # Keep the tiny manifest for reproducibility; the only large temporary
    # artifact is removed after every date above.


if __name__ == "__main__":
    main()
