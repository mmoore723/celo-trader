#!/usr/bin/env python3
"""Test a frozen QQQ confirmation gate on paid SPY Trend option outcomes.

This is a causal, research-only cross-market filter.  It does not generate a
new SPY signal or rescore one after seeing its result.  At each completed SPY
Trend Continuation signal it asks whether QQQ independently agrees through:

* a same-direction trailing 15-minute return;
* price on the same side of session VWAP; and
* a same-direction five-minute slope in QQQ EMA(9).

The exact already-paid SPY option ask-to-30-minute-bid outcomes are retained.
May is selection, June is validation, and July is final holdout.  There are no
threshold variants to choose among after results are visible.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.engine.data import load_csv
from research.jobs.tune_paid_strategy_holds import non_overlapping_rows


def _ema(values: list[float], length: int = 9) -> float:
    value, alpha = values[0], 2.0 / (length + 1.0)
    for item in values[1:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _vwap(bars) -> float:
    volumes = [max(float(bar.volume), 1.0) for bar in bars]
    return sum(
        ((bar.high + bar.low + bar.close) / 3.0) * volume
        for bar, volume in zip(bars, volumes)
    ) / sum(volumes)


def qqq_confirms(row: dict[str, object], qqq_by_day: dict[object, list]) -> tuple[bool, dict[str, float]] | None:
    """Return only context observable at the SPY signal timestamp."""
    signal_time = datetime.fromisoformat(str(row["signal_time"]))
    visible = [bar for bar in qqq_by_day.get(signal_time.date(), ()) if bar.timestamp <= signal_time]
    if len(visible) < 25:
        return None
    closes = [bar.close for bar in visible]
    return_15m = 100.0 * (closes[-1] / closes[-16] - 1.0)
    ema_now = _ema(closes[-9:])
    ema_five_minutes_ago = _ema(closes[-14:-5])
    session_vwap = _vwap(visible)
    side = str(row["side"]).lower()
    if side == "long":
        passed = return_15m > 0 and closes[-1] > session_vwap and ema_now > ema_five_minutes_ago
    elif side == "short":
        passed = return_15m < 0 and closes[-1] < session_vwap and ema_now < ema_five_minutes_ago
    else:
        raise ValueError(f"unsupported side: {side}")
    return passed, {
        "qqq_return_15m_pct": round(return_15m, 6),
        "qqq_close": round(closes[-1], 6),
        "qqq_vwap": round(session_vwap, 6),
        "qqq_ema9": round(ema_now, 6),
        "qqq_ema9_5m_ago": round(ema_five_minutes_ago, 6),
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    values = [float(row["return_pct"]) for row in rows]
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(values),
        "win_rate_pct": round(100 * sum(value > 0 for value in values) / len(values), 2) if values else None,
        "average_return_pct": round(statistics.fmean(values), 4) if values else None,
        "median_return_pct": round(statistics.median(values), 4) if values else None,
        "profit_factor": round(gains / losses, 4) if losses else (None if gains else 0.0),
        "total_return_points": round(sum(values), 4),
        "max_drawdown_points": round(drawdown, 4),
    }


def _period(row: dict[str, object]) -> str:
    month = datetime.fromisoformat(str(row["signal_time"])).month
    return {5: "selection_may", 6: "validation_june", 7: "holdout_july"}.get(month, "outside_protocol")


def _period_summaries(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[_period(row)].append(row)
    return {
        name: _summary(grouped.get(name, []))
        for name in ("selection_may", "validation_june", "holdout_july")
    }


def assess(source: dict[str, object], qqq_bars_path: Path) -> dict[str, object]:
    raw = list(source["markouts_by_hold"]["30"])
    baseline = non_overlapping_rows(raw)
    qqq_by_day = defaultdict(list)
    dataset = load_csv(qqq_bars_path)
    for bar in dataset.bars:
        qqq_by_day[bar.timestamp.date()].append(bar)
    confirmed, unavailable = [], 0
    for original in baseline:
        result = qqq_confirms(original, qqq_by_day)
        if result is None:
            unavailable += 1
            continue
        passed, context = result
        if passed:
            confirmed.append({**original, "qqq_confirmation": context})

    baseline_periods = _period_summaries(baseline)
    confirmed_periods = _period_summaries(confirmed)

    def profitable(summary, minimum):
        pf = summary["profit_factor"]
        return bool(
            int(summary["trades"]) >= minimum
            and float(summary["average_return_pct"] or 0) > 0
            and float(summary["median_return_pct"] or 0) > 0
            and (pf is None or float(pf) >= 1.20)
        )

    selected_before_holdout = profitable(confirmed_periods["selection_may"], 12) and profitable(
        confirmed_periods["validation_june"], 12
    )
    later, later_base = confirmed_periods["holdout_july"], baseline_periods["holdout_july"]
    holdout_retention = float(later["trades"]) / float(later_base["trades"] or 1)
    holdout_passed = bool(
        selected_before_holdout
        and profitable(later, 20)
        and holdout_retention >= 0.40
        and float(later["profit_factor"] or 0) >= float(later_base["profit_factor"] or 0)
        and float(later["average_return_pct"] or 0) >= float(later_base["average_return_pct"] or 0)
        and float(later["total_return_points"] or 0) >= 0.60 * float(later_base["total_return_points"] or 0)
        and float(later["max_drawdown_points"] or 0) <= float(later_base["max_drawdown_points"] or 0)
    )
    return {
        "complete": True,
        "runtime_changed": False,
        "strategy": "V2_SPY_TREND_CONT_WITH_QQQ_CONFIRMATION_V1",
        "purpose": "Frozen causal cross-index confirmation study using exact saved paid SPY option outcomes.",
        "rule": {
            "signal": "existing SPY Trend Continuation V2 signal",
            "confirmation": "QQQ trailing 15-minute return, session VWAP side, and five-minute EMA(9) slope all agree with SPY signal direction",
            "execution": "unchanged exact SPY next-minute ask and exact-contract 30-minute bid",
            "capacity": "one non-overlapping SPY position; this is not a one-trade-per-day rule",
        },
        "protocol": {
            "selection": "May: >=12 trades, positive mean/median, PF >=1.20",
            "validation": "June: same frozen gate",
            "holdout": "July: >=20 trades, >=40% retention, PF and average >= baseline, >=60% baseline total return, drawdown <= baseline",
        },
        "source_report": "paid_spy_trend_continuation_holds.json",
        "qqq_bars_path": str(qqq_bars_path),
        "qqq_bars_sha256": dataset.sha256,
        "baseline": {"periods": baseline_periods, "all": _summary(baseline)},
        "confirmed": {"periods": confirmed_periods, "all": _summary(confirmed), "rows": confirmed},
        "signals_without_qqq_context": unavailable,
        "holdout_retention_pct": round(100 * holdout_retention, 2),
        "selected_before_holdout": selected_before_holdout,
        "holdout_passed": holdout_passed,
        "decision": "qualify_for_integration_review" if holdout_passed else "reject_unchanged",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--qqq-bars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    report = assess(source, args.qqq_bars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "baseline": report["baseline"]["periods"],
        "confirmed": report["confirmed"]["periods"],
        "decision": report["decision"],
    }, indent=2))


if __name__ == "__main__":
    main()
