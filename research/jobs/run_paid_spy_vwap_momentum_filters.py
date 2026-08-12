#!/usr/bin/env python3
"""Compare VWAP-pullback momentum confirmation filters on paid SPY quotes.

This is a deliberately small, predeclared strategy study.  It tests the same
VWAP touch-and-reclaim setup four ways: base, RSI alignment, MACD alignment,
and both confirmations.  Every candidate buys a real SPY option ask and sells
that *same* contract at a real bid.  It never changes the running bot.

The earlier portion of the purchased period chooses a filter.  The later
portion is scored untouched.  A variant must have positive *average and
median* results on both portions; this avoids mistaking a couple of unusually
large wins for a repeatable setup.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.indicators import confirmed_signals
from research.engine.option_markouts import (
    run_databento_cbbo_markouts_for_labeled_signals,
    strategy_signals,
)
from research.engine.strategies import VWAPPullback
from research.engine.strategies.vwap_pullback import _vwaps
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file,
    result_row, write_checkpoint,
)


VARIANTS = ("base", "rsi_14_aligned", "macd_12_26_9_aligned", "rsi_and_macd_aligned")


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    returns = [float(row["return_pct"]) for row in rows]
    count = len(returns)
    return {
        "measured_signals": count,
        "positive_markouts": sum(value > 0 for value in returns),
        "win_rate_pct": round(sum(value > 0 for value in returns) / count * 100, 2) if count else None,
        "average_return_pct": round(sum(returns) / count, 4) if count else None,
        "median_return_pct": round(statistics.median(returns), 4) if count else None,
        "total_return_pct": round(sum(returns), 4),
    }


def _partition(rows: list[dict[str, object]], cutoff: date, training: bool) -> list[dict[str, object]]:
    return [
        row for row in rows
        if (datetime.fromisoformat(str(row["signal_time"])).date() < cutoff) is training
    ]


def segmented_summary(rows: list[dict[str, object]], holdout_start: date) -> dict[str, object]:
    return {
        "all": _summary(rows),
        "training": _summary(_partition(rows, holdout_start, True)),
        "holdout": _summary(_partition(rows, holdout_start, False)),
    }


def select_training_variant(
    markouts: dict[str, list[dict[str, object]]], holdout_start: date,
    minimum_training_signals: int = 10, minimum_holdout_signals: int = 5,
) -> dict[str, object]:
    """Select from earlier dates only and disclose a robust later check."""
    summaries = {name: segmented_summary(rows, holdout_start) for name, rows in markouts.items()}
    eligible = [
        name for name in VARIANTS
        if int(summaries[name]["training"]["measured_signals"]) >= minimum_training_signals
    ]
    if not eligible:
        return {
            "selected_variant": None,
            "reason": "too_few_training_signals",
            "minimum_training_signals": minimum_training_signals,
            "summaries": summaries,
        }
    winner = max(
        eligible,
        key=lambda name: (
            float(summaries[name]["training"]["median_return_pct"] or float("-inf")),
            float(summaries[name]["training"]["average_return_pct"] or float("-inf")),
            int(summaries[name]["training"]["measured_signals"]),
            -VARIANTS.index(name),
        ),
    )
    train, later = summaries[winner]["training"], summaries[winner]["holdout"]
    passed = (
        int(later["measured_signals"]) >= minimum_holdout_signals
        and float(train["average_return_pct"] or 0) > 0
        and float(train["median_return_pct"] or 0) > 0
        and float(later["average_return_pct"] or 0) > 0
        and float(later["median_return_pct"] or 0) > 0
    )
    return {
        "selected_variant": winner,
        "selection_rule": "earlier-data highest median option return; ties use average, sample size, then declared order",
        "later_data_gate": (
            f"at least {minimum_holdout_signals} later signals and positive average plus median return "
            "on both earlier and later data"
        ),
        "later_data_passed": passed,
        "minimum_training_signals": minimum_training_signals,
        "minimum_holdout_signals": minimum_holdout_signals,
        "summaries": summaries,
    }


def _distinct_touch_episodes(day_bars_, raw_signals):
    """Keep one entry per directional VWAP touch until price revisits VWAP.

    A reclaim can remain technically true for several consecutive one-minute
    bars.  Those are one setup, not several independent entries.  Once price
    returns to VWAP (or crosses it), that directional setup is re-armed and a
    later, separate pullback may qualify.  This is not a daily trade cap.
    """
    by_time = {signal.timestamp: signal for signal in raw_signals}
    vwaps = {bar.timestamp: vwap for bar, vwap in zip(day_bars_, _vwaps(day_bars_))}
    long_armed = short_armed = True
    output = []
    for bar in day_bars_:
        vwap = vwaps[bar.timestamp]
        if bar.close <= vwap:
            long_armed = True
        if bar.close >= vwap:
            short_armed = True
        signal = by_time.get(bar.timestamp)
        if signal is None:
            continue
        if signal.side.value == "long" and long_armed:
            output.append(signal)
            long_armed = False
        elif signal.side.value == "short" and short_armed:
            output.append(signal)
            short_armed = False
    return tuple(output)


def variants(day_bars_, prior_bars):
    """Return four filters for the same distinct touch-and-reclaim setups."""
    base = _distinct_touch_episodes(
        day_bars_, strategy_signals(day_bars_, VWAPPullback()),
    )
    chosen_times = {signal.timestamp for signal in base}
    def confirmed(**requirements):
        all_confirmed = confirmed_signals(
            day_bars_, VWAPPullback(), indicator_history=prior_bars, **requirements,
        )
        return tuple(signal for signal in all_confirmed if signal.timestamp in chosen_times)
    return {
        "base": base,
        "rsi_14_aligned": confirmed(require_rsi=True),
        "macd_12_26_9_aligned": confirmed(require_macd=True),
        "rsi_and_macd_aligned": confirmed(require_rsi=True, require_macd=True),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--hold-minutes", type=int, default=90)
    parser.add_argument("--min-dte", type=int, default=7)
    parser.add_argument("--max-dte", type=int, default=21)
    parser.add_argument("--min-premium", type=float, default=.80)
    parser.add_argument("--max-premium", type=float, default=10.0)
    parser.add_argument("--max-spread-pct", type=float, default=.08)
    parser.add_argument("--progress-every", type=int, default=5)
    args = parser.parse_args()
    if not args.archive.is_dir() or args.hold_minutes < 1:
        parser.error("an extracted paid archive and positive hold are required")

    dataset, filenames = load_csv(args.bars), archive_filenames(args.archive)
    existing = json.loads(args.output.read_text()) if args.output.exists() else {}
    completed = set(existing.get("processed_files", []))
    markouts = {name: list(existing.get("markouts_by_variant", {}).get(name, [])) for name in VARIANTS}
    signal_counts = {name: int(existing.get("underlying_signal_counts", {}).get(name, 0)) for name in VARIANTS}
    skipped = list(existing.get("skipped_files", []))
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "purpose": "Predeclared SPY VWAP-pullback RSI/MACD confirmation comparison using locally paid executable option quotes; research-only.",
        "data_source": f"local paid portal archive: {args.archive}",
        "ticker": "SPY", "strategy": "V2_VWAP_PULLBACK",
        "variants": list(VARIANTS), "holdout_start": args.holdout_start.isoformat(),
        "hold_minutes": args.hold_minutes,
        "entry": "completed 1-minute VWAP touch-and-reclaim/rejection; fill next minute",
        "filter_definition": "Long: RSI(14) >= 50 and/or MACD(12,26,9) histogram > 0. Short uses the inverse.",
        "execution": "entry at actual ask; same-contract exit at actual bid; no midpoint or synthetic option price",
        "causality": "strategy receives only current session; RSI/MACD receive preceding completed bars only",
        "bars_path": str(args.bars), "bars_sha256": dataset.sha256,
        "candidate_files": len(filenames),
        "eligibility": {"min_dte": args.min_dte, "max_dte": args.max_dte,
                        "min_premium": args.min_premium, "max_premium": args.max_premium,
                        "max_spread_pct": args.max_spread_pct},
    }
    for filename in filenames:
        if filename in completed:
            continue
        trading_day = batch_file_date(filename)
        day = day_bars(dataset, trading_day) if trading_day else ()
        prior = tuple(bar for bar in dataset.bars if day and bar.timestamp < day[0].timestamp)[-100:]
        labeled = variants(day, prior) if day else {name: () for name in VARIANTS}
        for name, signals in labeled.items():
            signal_counts[name] += len(signals)
        if not day:
            skipped.append({"filename": filename, "reason": "no_frozen_underlying_bars"})
        elif not labeled["base"]:
            skipped.append({"filename": filename, "reason": "no_vwap_pullback_signal"})
        else:
            raw_path = None
            try:
                raw_path = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
                results = run_databento_cbbo_markouts_for_labeled_signals(
                    day, [raw_path], labeled, "SPY", hold_minutes=args.hold_minutes,
                    min_dte=args.min_dte, max_dte=args.max_dte, min_premium=args.min_premium,
                    max_premium=args.max_premium, max_spread_pct=args.max_spread_pct,
                )
                for name, rows in results.items():
                    markouts[name].extend(result_row(row) for row in rows)
            finally:
                if raw_path is not None:
                    raw_path.unlink(missing_ok=True)
        completed.add(filename)
        selection = select_training_variant(markouts, args.holdout_start)
        write_checkpoint(args.output, {
            **base, "processed_files": sorted(completed), "skipped_files": skipped,
            "underlying_signal_counts": signal_counts, "markouts_by_variant": markouts,
            "selection": selection, "complete": len(completed) == len(filenames),
        })
        if len(completed) == len(filenames) or len(completed) % args.progress_every == 0:
            print(json.dumps({"processed": len(completed), "candidate_files": len(filenames),
                              "underlying_signal_counts": signal_counts,
                              "selected_variant": selection["selected_variant"], "latest_file": filename}), flush=True)


if __name__ == "__main__":
    main()
