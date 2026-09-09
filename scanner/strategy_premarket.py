"""Pure strategy-aware premarket context; never creates signals or orders.

The numeric value returned here is a readiness index used to sort the morning
report. It is not a probability, expected return, or backtest result. Actual
entry evaluators remain the only source of trade signals.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_exit_summary


def _price(row: Mapping[str, object], key: str = "c") -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _change(rows: Sequence[Mapping[str, object]], lookback: int) -> float | None:
    if not rows:
        return None
    current = _price(rows[-1])
    prior_index = max(0, len(rows) - 1 - lookback)
    prior = _price(rows[prior_index])
    return round((current - prior) / prior * 100, 2) if current > 0 and prior > 0 else None


def _completed_daily(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Exclude a partial current-day daily candle when its date is available."""
    if any("is_complete" in row for row in rows):
        return [row for row in rows if row.get("is_complete") is not False]
    return list(rows)


def _frame(label: str, change: float | None) -> dict:
    if change is None:
        return {"label": label, "bias": "unavailable", "change_pct": None}
    bias = "up" if change > 0.1 else "down" if change < -0.1 else "flat"
    return {"label": label, "bias": bias, "change_pct": change}


def multi_timeframe_context(
    *, minute_bars: Sequence[Mapping[str, object]],
    hourly_bars: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]],
    current_price: float,
) -> list[dict]:
    """Summarize only data available at request time—never future candles."""
    daily = _completed_daily(daily_bars)
    current = [{"c": current_price}] if current_price > 0 else []
    day_rows = daily[-1:] + current
    return [
        _frame("Minute", _change(list(minute_bars)[-16:], 15)),
        _frame("Hour", _change(list(hourly_bars)[-7:], 6)),
        _frame("Day", _change(day_rows, 1)),
        _frame("Week", _change(daily + current, 5)),
        _frame("Month", _change(daily + current, 21)),
    ]


def _alignment(context: Sequence[Mapping[str, object]]) -> tuple[str, int]:
    biases = [str(row.get("bias")) for row in context if row.get("bias") in {"up", "down"}]
    up, down = biases.count("up"), biases.count("down")
    return ("bullish", up) if up > down else ("bearish", down) if down > up else ("neutral", max(up, down))


def _compression(daily_bars: Sequence[Mapping[str, object]]) -> bool:
    complete = _completed_daily(daily_bars)
    if len(complete) < 7:
        return False
    ranges = [max(0.0, _price(row, "h") - _price(row, "l")) for row in complete[-7:]]
    positive = [value for value in ranges if value > 0]
    return bool(positive) and ranges[-1] > 0 and ranges[-1] == min(positive)


def _inside_day(daily_bars: Sequence[Mapping[str, object]]) -> bool:
    complete = _completed_daily(daily_bars)
    if len(complete) < 2:
        return False
    prior, before = complete[-1], complete[-2]
    return _price(prior, "h") <= _price(before, "h") and _price(prior, "l") >= _price(before, "l")


def _prior_range_lt_atr10(daily_bars: Sequence[Mapping[str, object]]) -> bool:
    complete = _completed_daily(daily_bars)
    if len(complete) < 10:
        return False
    recent = complete[-10:]
    true_ranges = []
    for index, row in enumerate(recent):
        high, low = _price(row, "h"), _price(row, "l")
        previous_close = _price(complete[-11 + index]) if len(complete) >= 11 else _price(recent[index - 1]) if index else 0
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)) if previous_close else high - low)
    prior_range = _price(complete[-1], "h") - _price(complete[-1], "l")
    return prior_range > 0 and prior_range < sum(true_ranges) / len(true_ranges)


def _kaufman(hourly_bars: Sequence[Mapping[str, object]], periods: int = 10) -> float | None:
    closes = [_price(row) for row in hourly_bars if _price(row) > 0]
    if len(closes) < periods + 1:
        return None
    window = closes[-(periods + 1):]
    path = sum(abs(right - left) for left, right in zip(window, window[1:]))
    return abs(window[-1] - window[0]) / path if path > 0 else 0.0


def _fit(strategy_id: str, *, context: Sequence[Mapping[str, object]],
         daily_bars: Sequence[Mapping[str, object]], gap_pct: float,
         rvol: float, hourly_bars: Sequence[Mapping[str, object]]) -> tuple[int, str, str]:
    direction, agreeing = _alignment(context)
    volume_points = min(15, round(max(0.0, rvol - 0.8) * 10))
    trend_points = agreeing * 7
    compressed = _compression(daily_bars)

    if strategy_id == "CTX_ORB_NR7_OR_INSIDE":
        context_ready = compressed or _inside_day(daily_bars)
        score = 35 + volume_points + (40 if context_ready else 0)
        reason = "Yesterday had the smallest range in seven days or stayed inside the day before. Now wait for the opening breakout and strong volume." if context_ready else "Yesterday was not an NR7 or inside day, so this setup is a weaker fit today."
    elif strategy_id == "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG":
        context_ready = _prior_range_lt_atr10(daily_bars)
        score = 35 + volume_points + (40 if context_ready else 0)
        reason = "Yesterday moved less than its usual 10-day range. Now wait for the opening breakout and strong volume." if context_ready else "Yesterday moved more than this setup allows, so it is a weaker fit today."
    elif strategy_id == "V2_ORB_PULLBACK":
        score = 45 + volume_points + trend_points + min(8, round(abs(gap_pct) * 2))
        reason = "The morning trend looks useful. The bot still needs a clean opening-range break and the first pullback after the open."
    elif strategy_id in {"V2_SPY_TREND_CONT", "V2_TSLA_TWO_LEG_TREND_PULLBACK", "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"}:
        score = 38 + trend_points + volume_points + (8 if direction != "neutral" else 0)
        reason = f"{agreeing} of 5 time views point {direction}. The bot still waits for this strategy's exact entry pattern."
    elif strategy_id == "V2_SPY_AFTERNOON_FVG":
        score = 46 + trend_points + volume_points
        reason = "The bigger trend is being checked now. This setup only looks for an entry from 1:30 to 3:00 PM."
    elif strategy_id == "V2_FAILED_OR_BREAK_VWAP_REVERSION":
        score = 48 + volume_points + (14 if abs(gap_pct) < 1.5 else 2)
        reason = "The bot will watch for an opening break that fails, then comes back above or below VWAP. No entry can happen yet."
    elif strategy_id == "CTX_VWAP_PULLBACK_KER10_LONG":
        ker = _kaufman(hourly_bars)
        score = 30 + trend_points + volume_points + (35 if ker is not None and ker > 0.60 else 0)
        reason = f"The one-hour trend-efficiency score is {ker:.2f}. The exact KER rule will be checked again before any entry." if ker is not None else "The bot needs 11 one-hour closes before it can measure trend efficiency (KER)."
    elif strategy_id == "CTX_1H_SQUEEZE_MACD_LONG":
        score = 38 + trend_points + volume_points
        reason = "The bot is checking for tight one-hour price bands. It still needs a finished hourly candle and a rising MACD breakout."
    else:
        score, reason = 35 + trend_points + volume_points, "Waiting for this strategy's exact trigger."
    return max(0, min(100, score)), direction, reason


_ENTRY = {
    "V2_ORB_PULLBACK": "After 9:45, price must break the opening range, pull back to it once, then finish a one-minute candle in the breakout direction.",
    "V2_SPY_TREND_CONT": "A five-minute candle must finish the reviewed continuation pattern in the trend direction.",
    "V2_SPY_AFTERNOON_FVG": "Nothing in the morning. From 1:30–3:00 PM, price must return to the reviewed fair-value gap and confirm the move.",
    "V2_FAILED_OR_BREAK_VWAP_REVERSION": "Price must break the opening range, fail, then cross back over VWAP with confirmation.",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": "Price must make two clear pullback legs, stay on the correct side of VWAP, then finish a candle back with the trend.",
    "CTX_ORB_NR7_OR_INSIDE": "After 9:45, price must break the opening range and the breakout candle needs the required volume.",
    "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG": "After 9:45, yesterday's range check must pass and price must confirm an opening-range break.",
    "CTX_VWAP_PULLBACK_KER10_LONG": "After a clean trend forms, the KER check must pass and a five-minute candle must reclaim VWAP and EMA 9.",
    "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG": "After 10:30, price must move away from VWAP, touch it again, then finish a five-minute candle above EMA 9.",
    "CTX_1H_SQUEEZE_MACD_LONG": "A finished one-hour candle must break the squeeze while the MACD bars are above zero and rising.",
}


def strategy_aware_plan(
    *, ticker: str, context: Sequence[Mapping[str, object]],
    daily_bars: Sequence[Mapping[str, object]], gap_pct: float, rvol: float,
    executable_strategy_ids: Iterable[str], research_strategy_ids: Iterable[str],
    hourly_bars: Sequence[Mapping[str, object]] = (),
) -> dict:
    executable = {str(value).upper() for value in executable_strategy_ids}
    research = {str(value).upper() for value in research_strategy_ids}
    candidates = sorted(executable | research)
    matches = []
    for strategy_id in candidates:
        rule = REVIEWED_STRATEGIES.get(strategy_id)
        if rule is None:
            continue
        score, direction, reason = _fit(
            strategy_id, context=context, daily_bars=daily_bars,
            gap_pct=gap_pct, rvol=rvol, hourly_bars=hourly_bars,
        )
        matches.append({
            "strategy_id": strategy_id, "name": rule.display_name,
            "fit_score": score, "readiness_score": score, "direction": direction,
            "can_trade": strategy_id in executable, "reason": reason,
        })
    matches.sort(key=lambda row: (bool(row["can_trade"]), int(row["fit_score"])), reverse=True)
    best = matches[0] if matches else None
    if best is None:
        return {
            "fit_score": 0, "readiness_score": 0, "direction": "neutral", "tradeable_today": False,
            "best_strategy": None, "strategy_matches": [],
            "entry_note": "No reviewed strategy is available for this ticker yet.",
            "stop_note": "No entry means no stop.", "target_note": "Research collection continues.",
            "setup_notes": "Research only. This ticker cannot place an order from this report.",
        }
    strategy_id = str(best["strategy_id"])
    tradeable = bool(best["can_trade"])
    direction = str(best["direction"])
    if not tradeable:
        entry_note = "Research only—this ticker/strategy pair cannot place an order."
        stop_note = "No order is authorized."
        target_note = reviewed_exit_summary(strategy_id, verb="measure")
    else:
        entry_note = _ENTRY.get(strategy_id, "Wait for the strategy's exact intraday trigger.")
        stop_note = "Use the strategy's tested exit rule. The bot does not make up a stop before the entry exists."
        target_note = reviewed_exit_summary(strategy_id)
    return {
        "fit_score": int(best["fit_score"]), "readiness_score": int(best["fit_score"]), "direction": direction,
        "tradeable_today": tradeable, "best_strategy": best,
        "strategy_matches": matches[:5], "entry_note": entry_note,
        "stop_note": stop_note, "target_note": target_note,
        "setup_notes": str(best["reason"]),
    }
