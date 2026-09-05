#!/usr/bin/env python3
"""Rebuild the exact option cohort reachable by deployed SPY Trend rules.

The original paid report contains every non-overlapping option markout emitted
by the raw five-minute signal primitive. Production additionally suppresses a
continuing breakout, reserves the afternoon SPY slot, and applies the reviewed
three-candle entry gate. This job replays those controls in their real order,
fails if the frozen reconciliation counts drift, and saves the surviving rows
for account-level launch audits.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys
from typing import Any, Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import BarDataset, load_csv
from strategies.market_structure import (
    Bar,
    Side,
    StructureSignal,
    TrendContinuation,
    TrendContinuationConfig,
    resample_regular_session,
)
from trading.portfolio_policy import (
    reviewed_portfolio_entry_policy,
    reviewed_strategy_entry_policy,
)


STRATEGY_ID = "V2_SPY_TREND_CONT"
TICKER = "SPY"
MARKET_TIMEZONE = ZoneInfo("America/New_York")
SLIPPAGE_PRICE_PER_SIDE = 0.01
FEE_PER_CONTRACT_PER_SIDE = 0.12
EXPECTED_COUNTS = {
    "source_option_markouts": 156,
    "source_markouts_matching_raw_primitive": 156,
    "source_markouts_reachable_after_breakout_state": 86,
    "source_markouts_after_afternoon_slot_reservation": 72,
    "source_markouts_after_three_candle_gate": 46,
}

SignalEvaluator = Callable[[Sequence[Bar]], StructureSignal | None]


def _signal_key(timestamp: object, side: object) -> tuple[str, str]:
    moment = datetime.fromisoformat(str(timestamp)) if not isinstance(timestamp, datetime) else timestamp
    normalized_side = str(getattr(side, "value", side)).strip().lower()
    return moment.isoformat(), normalized_side


def replay_session_signals(
    five_minute_bars: Sequence[Bar], *, evaluator: SignalEvaluator | None = None,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Return raw and production-emitted signals for one chronological session."""
    config = TrendContinuationConfig()
    strategy_evaluator = evaluator or TrendContinuation(config).evaluate
    minimum = max(config.slow_ema, config.atr_bars + 1, config.breakout_bars + 1)
    active_breakout: tuple[Side, float] | None = None
    raw: dict[tuple[str, str], dict[str, Any]] = {}
    emitted: dict[tuple[str, str], dict[str, Any]] = {}

    for end_index in range(minimum - 1, len(five_minute_bars)):
        history = five_minute_bars[:end_index + 1]
        current = history[-1]
        if active_breakout is not None:
            active_side, broken_level = active_breakout
            reset = (
                (active_side is Side.LONG and current.close <= broken_level)
                or (active_side is Side.SHORT and current.close >= broken_level)
            )
            if reset:
                active_breakout = None

        candidate = strategy_evaluator(history)
        if candidate is None:
            continue
        key = _signal_key(candidate.timestamp, candidate.side)
        details = {
            "direction": "bullish" if candidate.side is Side.LONG else "bearish",
            "signal_meta": dict(candidate.features),
        }
        raw[key] = details
        if active_breakout is not None and active_breakout[0] is candidate.side:
            continue
        level_name = "prior_high" if candidate.side is Side.LONG else "prior_low"
        broken_level = candidate.features.get(level_name)
        if broken_level is None:
            continue
        emitted[key] = details
        active_breakout = candidate.side, float(broken_level)
    return raw, emitted


def replay_production_signals(
    one_minute_bars: Iterable[Bar],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Replay the production adapter's session-isolated breakout state."""
    sessions: dict[object, list[Bar]] = defaultdict(list)
    for bar in one_minute_bars:
        sessions[bar.timestamp.date()].append(bar)
    raw: dict[tuple[str, str], dict[str, Any]] = {}
    emitted: dict[tuple[str, str], dict[str, Any]] = {}
    for session_bars in sessions.values():
        five_minute = resample_regular_session(session_bars, 1, 5)
        session_raw, session_emitted = replay_session_signals(five_minute)
        raw.update(session_raw)
        emitted.update(session_emitted)
    return raw, emitted


def _market_moment(value: object) -> datetime:
    moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MARKET_TIMEZONE)
    return moment.astimezone(MARKET_TIMEZONE)


def _one_contract_pnl(row: dict[str, Any]) -> float:
    entry = float(row["entry_ask"]) + SLIPPAGE_PRICE_PER_SIDE
    exit_price = max(0.0, float(row["exit_bid"]) - SLIPPAGE_PRICE_PER_SIDE)
    return (exit_price - entry) * 100 - 2 * FEE_PER_CONTRACT_PER_SIDE


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_one_contract_pnl(row) for row in rows]
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    return {
        "trades": len(rows),
        "raw_quote_wins_before_costs": sum(float(row["exit_bid"]) > float(row["entry_ask"]) for row in rows),
        "wins_after_costs": sum(value > 0 for value in pnls),
        "win_rate_after_costs_pct": round(100 * sum(value > 0 for value in pnls) / len(pnls), 2) if pnls else None,
        "net_pnl_one_contract_after_costs": round(sum(pnls), 2),
        "median_pnl_one_contract_after_costs": round(median(pnls), 2) if pnls else None,
        "profit_factor_after_costs": round(gains / losses, 4) if losses else ("inf" if gains else None),
    }


def _fingerprint(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


def build_report(
    source: dict[str, Any], bars: BarDataset, *, source_path: Path,
    runtime_root: Path, enforce_frozen_counts: bool = True,
) -> dict[str, Any]:
    if not source.get("complete"):
        raise ValueError("source option study is incomplete")
    source_rows = source.get("markouts_by_hold", {}).get("30")
    if not isinstance(source_rows, list):
        raise ValueError("source study has no markouts_by_hold.30 list")
    if source.get("bars_sha256") and source["bars_sha256"] != bars.sha256:
        raise ValueError("source study and supplied bars have different hashes")

    raw_signals, emitted_signals = replay_production_signals(bars.bars)
    source_keys = [_signal_key(row["signal_time"], row["side"]) for row in source_rows]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("source option markouts do not have unique signal/side keys")
    raw_matches = [row for row, key in zip(source_rows, source_keys) if key in raw_signals]
    reachable: list[dict[str, Any]] = []
    for row, key in zip(source_rows, source_keys):
        details = emitted_signals.get(key)
        if details is not None:
            reachable.append({**row, **details})

    after_reservation = [
        row for row in reachable
        if reviewed_portfolio_entry_policy(
            ticker=TICKER,
            strategy_id=STRATEGY_ID,
            now_et=_market_moment(row["entry_time"]),
            settings={"strategy_spy_afternoon_fvg_v2_enabled": True},
        ).allowed
    ]
    after_structure = [
        row for row in after_reservation
        if reviewed_strategy_entry_policy(
            ticker=TICKER,
            strategy_id=STRATEGY_ID,
            direction=row["direction"],
            signal_meta=row["signal_meta"],
        ).allowed
    ]
    counts = {
        "source_option_markouts": len(source_rows),
        "source_markouts_matching_raw_primitive": len(raw_matches),
        "source_markouts_reachable_after_breakout_state": len(reachable),
        "source_markouts_after_afternoon_slot_reservation": len(after_reservation),
        "source_markouts_after_three_candle_gate": len(after_structure),
        "all_raw_primitive_signals": len(raw_signals),
        "all_production_emitted_signals": len(emitted_signals),
    }
    if enforce_frozen_counts:
        drift = {
            key: {"expected": expected, "actual": counts.get(key)}
            for key, expected in EXPECTED_COUNTS.items()
            if counts.get(key) != expected
        }
        if drift:
            raise ValueError(f"deployed cohort reconciliation drifted: {drift}")

    enriched_rows = [
        {
            **row,
            "after_cost_pnl_one_contract": round(_one_contract_pnl(row), 2),
            "cost_model": {
                "slippage_price_per_side": SLIPPAGE_PRICE_PER_SIDE,
                "fee_per_contract_per_side": FEE_PER_CONTRACT_PER_SIDE,
            },
        }
        for row in after_structure
    ]
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched_rows:
        by_month[datetime.fromisoformat(str(row["signal_time"])).strftime("%Y-%m")].append(row)

    runtime_sources = [
        runtime_root / "strategies/market_structure.py",
        runtime_root / "strategies/spy_trend_continuation_v2.py",
        runtime_root / "trading/portfolio_policy.py",
    ]
    return {
        "purpose": "Exact machine-reproducible paid-option cohort reachable by deployed SPY Trend rules.",
        "complete": True,
        "ticker": TICKER,
        "strategy": STRATEGY_ID,
        "source_report": str(source_path),
        "bars_path": bars.source_path,
        "bars_sha256": bars.sha256,
        "runtime_sources": [_fingerprint(path) for path in runtime_sources],
        "methodology": {
            "order": [
                "raw five-minute TrendContinuation signal",
                "same-breakout suppression until a completed close re-arms it",
                "13:45 through 15:00 ET SPY slot reservation",
                "calls require three consecutive higher lows; puts require three consecutive lower highs",
            ],
            "entry": "recorded option ask plus $0.01 adverse slippage",
            "exit": "same-contract recorded option bid after 30 minutes minus $0.01 adverse slippage",
            "fees": "$0.12 per contract per side",
        },
        "reconciliation": counts,
        "summary": summarize(enriched_rows),
        "summary_by_month": {month: summarize(rows) for month, rows in sorted(by_month.items())},
        "markouts_by_hold": {"30": enriched_rows},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--allow-count-drift", action="store_true")
    args = parser.parse_args()
    report = build_report(
        json.loads(args.source.read_text(encoding="utf-8")),
        load_csv(args.bars),
        source_path=args.source,
        runtime_root=args.runtime_root,
        enforce_frozen_counts=not args.allow_count_drift,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"reconciliation": report["reconciliation"], "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
