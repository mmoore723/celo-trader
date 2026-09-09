#!/usr/bin/env python3
"""Compare dynamic exits on fixed TSLA Two-Leg entries and contracts.

This job is research-only.  It replays the current production entry rule,
preserves the paid study's exact option contract and ask, and changes only the
time at which the same contract is marked at its first real bid.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.engine.fixed_contract_exits import ExactContractEpisode, price_exact_contract_exits
from research.engine.models import Bar, Side, Signal
from research.engine.two_leg_dynamic_exits import RULES, planned_two_leg_dynamic_exits
from research.jobs.assess_tsla_two_leg_dynamic_exits import assess, comparable_rows
from research.jobs.run_paid_databento_job import (
    archive_filenames, batch_file_date, day_bars, extract_archive_file, write_checkpoint,
)
from trading.two_leg_trend_pullback_execution import _Bar, _signal_at_latest_bar


def _production_bars(bars: tuple[Bar, ...]) -> dict[date, tuple[_Bar, ...]]:
    by_day: dict[date, list[_Bar]] = defaultdict(list)
    for bar in bars:
        if time(9, 30) <= bar.timestamp.time() <= time(15, 59):
            by_day[bar.timestamp.date()].append(_Bar(
                pd.Timestamp(bar.timestamp), bar.open, bar.high, bar.low,
                bar.close, bar.volume, 0.0,
            ))
    return {day: tuple(values) for day, values in by_day.items()}


def fixed_current_episodes(
    source_rows: list[dict[str, object]], bars: tuple[Bar, ...],
) -> tuple[tuple[ExactContractEpisode, Signal, Bar, dict[str, object]], ...]:
    """Keep only rows reproduced by the current production entry rule."""
    production = _production_bars(bars)
    output = []
    for row in source_rows:
        signal_time = datetime.fromisoformat(str(row["signal_time"]))
        visible = tuple(
            bar for bar in production.get(signal_time.date(), ())
            if bar.timestamp <= pd.Timestamp(signal_time)
        )
        live_signal = _signal_at_latest_bar(visible)
        expected_direction = "bullish" if row["side"] == "long" else "bearish"
        if (live_signal is None or live_signal.trigger_bar != pd.Timestamp(signal_time)
                or live_signal.direction != expected_direction):
            continue
        side = Side.LONG if expected_direction == "bullish" else Side.SHORT
        signal = Signal(
            live_signal.strategy_id, side, signal_time,
            float(live_signal.meta["v2_entry_reference"]),
            float(live_signal.meta["v2_stop"]), float(live_signal.meta["v2_target"]),
            dict(live_signal.meta),
        )
        entry_bar = next(
            (bar for bar in bars if bar.timestamp.date() == signal_time.date()
             and bar.timestamp > signal_time), None,
        )
        if entry_bar is None:
            continue
        episode = ExactContractEpisode(
            signal_time, datetime.fromisoformat(str(row["entry_time"])),
            str(row["contract"]), float(row["entry_ask"]),
        )
        output.append((episode, signal, entry_bar, row))
    return tuple(output)


def _with_costs(row: dict[str, object], fee: float, slippage: float) -> dict[str, object]:
    entry = float(row["entry_ask"])
    bid = float(row["exit_bid"])
    entry_cost = entry * 100 + fee + slippage * 100
    proceeds = bid * 100 - fee - slippage * 100
    pnl = proceeds - entry_cost
    return {**row, "net_pnl_one_contract": round(pnl, 6),
            "net_return_pct": round(100 * pnl / entry_cost, 6)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--fee-per-contract-per-side", type=float, default=.65)
    parser.add_argument("--slippage-price-per-side", type=float, default=.01)
    parser.add_argument("--max-exit-wait-minutes", type=int, default=5)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()
    if not (args.archive.is_file() or args.archive.is_dir()):
        parser.error("paid archive must exist")
    if (min(args.fee_per_contract_per_side, args.slippage_price_per_side) < 0
            or args.max_exit_wait_minutes < 1 or args.progress_every < 1):
        parser.error("costs must be nonnegative and minute/progress limits must be positive")

    dataset = load_csv(args.bars)
    source = json.loads(args.source_report.read_text())
    source_rows = source["markouts_by_variant_hold"]["baseline"]["90"]
    episodes = fixed_current_episodes(source_rows, dataset.bars)
    files_by_day = {
        batch_file_date(name): name for name in archive_filenames(args.archive)
        if batch_file_date(name) is not None
    }
    prior = json.loads(args.output.read_text()) if args.output.exists() else {}
    if prior and int(prior.get("max_exit_wait_minutes", -1)) != args.max_exit_wait_minutes:
        raise RuntimeError("checkpoint uses a different max exit wait; choose a new output path")
    completed = set(prior.get("processed_signals", []))
    raw = prior.get("markouts_by_rule", {})
    rows_by_rule = {rule: list(raw.get(rule, [])) for rule in RULES}
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    holdout_start = date.fromisoformat(str(source["holdout_start"]))
    base = {
        "purpose": "research-only exit comparison; no broker or strategy configuration changes",
        "strategy": "V2_TSLA_TWO_LEG_TREND_PULLBACK", "ticker": "TSLA",
        "source_report": str(args.source_report), "bars_path": str(args.bars),
        "bars_sha256": dataset.sha256, "source_outcomes": len(source_rows),
        "current_entry_outcomes": len(episodes), "holdout_start": holdout_start.isoformat(),
        "entry_and_contract": "exact current production entry replay; original paid contract, time, and ask are fixed",
        "execution": f"same contract exits at first real bid within {args.max_exit_wait_minutes} minutes; actual quote delay is disclosed; no midpoint or synthetic fill",
        "costs": {"fee_per_contract_per_side": args.fee_per_contract_per_side,
                  "slippage_price_per_side": args.slippage_price_per_side},
        "max_exit_wait_minutes": args.max_exit_wait_minutes,
        "exit_definitions": {
            "fixed_90m": "unchanged 90-minute control",
            "structural_stop_90m": "completed candle touches original structural invalidation; otherwise 90 minutes",
            "confirmed_vwap_ema_90m": "two completed closes lose both VWAP and EMA(9); otherwise 90 minutes",
            "armed_chandelier_3atr_90m": "after a completed close reaches +1R, later closes trail the best price by 3 ATR; otherwise 90 minutes",
            "hybrid_armed_chandelier_vwap_ema_90m": "first structural, confirmed VWAP/EMA, or armed 3-ATR exit; otherwise 90 minutes",
        },
    }
    for index, (episode, signal, entry_bar, original) in enumerate(episodes, start=1):
        key = episode.signal_time.isoformat()
        if key in completed:
            continue
        filename = files_by_day.get(episode.signal_time.date())
        if filename is None:
            raise RuntimeError(f"paid archive has no file for {episode.signal_time.date()}")
        bars = day_bars(dataset, episode.signal_time.date())
        plans = planned_two_leg_dynamic_exits(bars, signal, entry_bar)
        staged = extract_archive_file(args.archive, filename, args.scratch_dir / filename)
        try:
            results = price_exact_contract_exits(
                staged, episode, plans,
                max_wait=timedelta(minutes=args.max_exit_wait_minutes),
            )
        finally:
            staged.unlink(missing_ok=True)
        for rule, row in results.items():
            enriched = _with_costs(row, args.fee_per_contract_per_side, args.slippage_price_per_side)
            enriched["original_fixed_exit_bid"] = original["exit_bid"]
            rows_by_rule[rule].append(enriched)
        completed.add(key)
        comparison = comparable_rows(rows_by_rule)
        payload = {**base, "processed_signals": sorted(completed),
                   "markouts_by_rule": rows_by_rule,
                   "assessment": assess(comparison, holdout_start),
                   "complete": len(completed) == len(episodes)}
        write_checkpoint(args.output, payload)
        if index % args.progress_every == 0 or len(completed) == len(episodes):
            print(json.dumps({"processed": len(completed), "total": len(episodes),
                              "date": episode.signal_time.date().isoformat(),
                              "decision": payload["assessment"]["decision"]}), flush=True)


if __name__ == "__main__":
    main()
