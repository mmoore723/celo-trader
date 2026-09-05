#!/usr/bin/env python3
"""Audit causal trigger-candle confirmations for SPY Afternoon FVG.

The paid FVG report labels a completed five-minute setup with the final minute
inside that candle (for example, the 13:30 candle is labeled 13:34 so the
option engine can seek its first quote at 13:35).  This audit therefore includes
that completed candle when reconstructing price-action context.  Older generic
context audits compared ``bucket close <= signal label`` and accidentally
described the prior five-minute candle instead.

This is a retrospective repair diagnostic.  It reports actual paid ask-to-bid
outcomes after the production slippage and fee model; it never changes a saved
strategy setting and does not call historical results prospective validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import statistics
import sys
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.market_constants import COMMISSION_PER_CONTRACT
from research.engine.data import load_csv, resample_regular_session
from strategies import spy_afternoon_fvg_v2
from strategies.market_structure import Bar
from strategies.price_action_context import PriceActionContext, describe_price_action


SLIPPAGE_PER_SIDE = 0.01
VARIANTS = ("baseline", "close_on_fast_ema_side", "decisive_close_60_40")


def _rows_at_path(payload: object, path: str) -> list[dict[str, object]]:
    value = payload
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    if not isinstance(value, list):
        raise ValueError("rows-path must resolve to a list")
    return value


def _ema(values: Sequence[float], length: int) -> float:
    if not values:
        raise ValueError("EMA needs at least one value")
    value = float(values[0])
    alpha = 2.0 / (length + 1.0)
    for item in values[1:]:
        value = alpha * float(item) + (1.0 - alpha) * value
    return value


def _atr(bars: Sequence[Bar], length: int = 14) -> float:
    relevant = bars[-(length + 1):]
    values = [
        max(right.high - right.low, abs(right.high - left.close), abs(right.low - left.close))
        for left, right in zip(relevant, relevant[1:])
    ]
    return sum(values) / len(values) if values else 0.0


def _vwap(bars: Sequence[Bar]) -> float:
    volumes = [max(float(bar.volume), 1.0) for bar in bars]
    return sum(
        ((bar.high + bar.low + bar.close) / 3.0) * volume
        for bar, volume in zip(bars, volumes)
    ) / sum(volumes)


def _visible_five_minute_bars(
    row: dict[str, object], one_minute_bars: Sequence[Bar],
) -> tuple[Bar, ...]:
    signal_time = datetime.fromisoformat(str(row["signal_time"]))
    session = tuple(
        bar for bar in one_minute_bars if bar.timestamp.date() == signal_time.date()
    )
    five_minute = resample_regular_session(
        session, source_minutes=1, target_minutes=5,
    )
    # The report's signal label is minute 5 of the trigger bucket.  At the next
    # minute's entry the full bucket is complete and causally visible.
    return tuple(
        bar for bar in five_minute
        if bar.timestamp + timedelta(minutes=5) <= signal_time + timedelta(minutes=1)
    )


def trigger_context(
    row: dict[str, object], one_minute_bars: Sequence[Bar],
) -> PriceActionContext:
    """Describe the completed five-minute candle that created ``row``."""
    signal_time = datetime.fromisoformat(str(row["signal_time"]))
    visible = _visible_five_minute_bars(row, one_minute_bars)
    if len(visible) < 21:
        raise ValueError(f"insufficient completed context for {signal_time.isoformat()}")
    atr = _atr(visible)
    if atr <= 0:
        raise ValueError(f"non-positive ATR for {signal_time.isoformat()}")
    closes = [bar.close for bar in visible[-20:]]
    return describe_price_action(
        visible,
        atr=atr,
        fast_ema=_ema(closes[-8:], 8),
        slow_ema=_ema(closes, 20),
        vwap=_vwap(visible),
        pivot_wing=2,
    )


def _passes(
    variant: str, row: dict[str, object], context: PriceActionContext,
) -> bool:
    if variant == "baseline":
        return True
    long = str(row["side"]) == "long"
    if variant == "close_on_fast_ema_side":
        distance = float(context.close_to_fast_ema_atr or 0.0)
        return distance > 0.0 if long else distance < 0.0
    if variant == "decisive_close_60_40":
        return context.close_location >= 0.60 if long else context.close_location <= 0.40
    raise ValueError(f"unknown variant: {variant}")


def _net_pnl(row: dict[str, object]) -> float:
    entry = float(row["entry_ask"]) + SLIPPAGE_PER_SIDE
    exit_price = max(0.0, float(row["exit_bid"]) - SLIPPAGE_PER_SIDE)
    return (exit_price - entry) * 100.0 - 2.0 * COMMISSION_PER_CONTRACT


def _summary(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    values = [_net_pnl(row) for row in rows]
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    return {
        "trades": len(values),
        "wins": sum(value > 0 for value in values),
        "win_rate_pct": round(100.0 * sum(value > 0 for value in values) / len(values), 2)
        if values else None,
        "net_pnl_one_contract": round(sum(values), 2),
        "average_pnl_one_contract": round(statistics.mean(values), 2) if values else None,
        "median_pnl_one_contract": round(statistics.median(values), 2) if values else None,
        "profit_factor": round(gains / losses, 4) if losses else (None if gains else 0.0),
    }


def audit(
    rows: Sequence[dict[str, object]], one_minute_bars: Sequence[Bar], *,
    holdout_start: str = "2026-07-01",
) -> dict[str, object]:
    enriched: list[tuple[dict[str, object], PriceActionContext]] = [
        (row, trigger_context(row, one_minute_bars)) for row in rows
    ]
    production_replay_mismatches = []
    for row, context in enriched:
        candidate = spy_afternoon_fvg_v2._signal_from_completed_bars(
            _visible_five_minute_bars(row, one_minute_bars),
        )
        expected = _passes("close_on_fast_ema_side", row, context)
        expected_direction = "bullish" if str(row["side"]) == "long" else "bearish"
        actual = bool(candidate and candidate.direction == expected_direction)
        if actual != expected:
            production_replay_mismatches.append({
                "signal_time": str(row["signal_time"]),
                "expected": expected,
                "actual_direction": candidate.direction if candidate else None,
            })
    months = sorted({str(row["signal_time"])[:7] for row, _context in enriched})
    summaries: dict[str, object] = {}
    accepted_times: dict[str, list[str]] = {}
    for variant in VARIANTS:
        accepted = [
            row for row, context in enriched if _passes(variant, row, context)
        ]
        summaries[variant] = {
            "all": _summary(accepted),
            "training": _summary([
                row for row in accepted if str(row["signal_time"])[:10] < holdout_start
            ]),
            "holdout": _summary([
                row for row in accepted if str(row["signal_time"])[:10] >= holdout_start
            ]),
            "by_month": {
                month: _summary([
                    row for row in accepted if str(row["signal_time"]).startswith(month)
                ])
                for month in months
            },
        }
        accepted_times[variant] = [str(row["signal_time"]) for row in accepted]
    return {
        "purpose": "Retrospective causal repair audit for the SPY Afternoon FVG trigger candle.",
        "context_clock": (
            "A five-minute candle labeled by its final constituent minute is included at the next-minute entry."
        ),
        "execution_model": (
            "Actual option ask plus $0.01 entry slippage to same-contract bid minus $0.01 exit slippage; "
            f"${COMMISSION_PER_CONTRACT:.2f} fee per side."
        ),
        "variants": list(VARIANTS),
        "holdout_start": holdout_start,
        "source_rows": len(rows),
        "summaries": summaries,
        "accepted_signal_times": accepted_times,
        "production_replay_mismatches": production_replay_mismatches,
        "decision": (
            "close_on_fast_ema_side is a paper-repair candidate only; historical results remain "
            "retrospective and require fresh forward validation"
        ),
        "complete": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--rows-path", required=True)
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-start", default="2026-07-01")
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    rows = _rows_at_path(source, args.rows_path)
    result = audit(rows, load_csv(args.bars).bars, holdout_start=args.holdout_start)
    if result["production_replay_mismatches"]:
        raise AssertionError(
            "production evaluator does not reproduce the audited EMA8 cohort: "
            f"{result['production_replay_mismatches']}"
        )
    result["source_report"] = str(args.input)
    result["rows_path"] = args.rows_path
    result["bars_path"] = str(args.bars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summaries"], indent=2))


if __name__ == "__main__":
    main()
