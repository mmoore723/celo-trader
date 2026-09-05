"""Exact, fail-closed evaluators for the context-strategy research matrix.

These evaluators reproduce the frozen signal premises tested in
``research/engine/context_strategy_matrix.py``. Most catalog entries are
``observation_only`` and can never reach order code. VWAP 10:30 Displacement
has a separately reviewed paper-execution version; the server catalog remains
the authority for that promotion.

The current-session DataFrame carries a compact multi-session OHLCV tape in
``DataFrame.attrs``.  If that context is absent or incomplete, every evaluator
returns ``None`` rather than weakening NR7, ATR, KER, or squeeze conditions.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
import math
import statistics
from typing import Callable, Sequence

import pandas as pd

from strategies.base import Signal
from strategies.market_structure import Bar, resample_regular_session
from strategies.spy_trend_continuation_v2 import _complete_five_minute_bars, _execution_scope


ORB_NR7_INSIDE = "CTX_ORB_NR7_OR_INSIDE"
ORB_ATR10_LONG = "CTX_ORB_PRIOR_RANGE_LT_ATR10_LONG"
VWAP_KER10_LONG = "CTX_VWAP_PULLBACK_KER10_LONG"
VWAP_DISPLACEMENT_LONG = "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"
SQUEEZE_MACD_LONG = "CTX_1H_SQUEEZE_MACD_LONG"

_ORB_TICKERS = frozenset({"SPY", "QQQ", "TSLA", "AMZN"})
_VWAP_KER_TICKERS = frozenset({"SPY", "QQQ", "TSLA", "AMZN"})
_VWAP_DISPLACEMENT_TICKERS = frozenset({"TSLA", "AMZN"})
_SQUEEZE_TICKERS = frozenset({"QQQ"})
_emitted: set[tuple[str, str, str, str]] = set()


def _normalized_times(values: pd.Series) -> pd.Series:
    times = pd.to_datetime(values)
    try:
        if times.dt.tz is not None:
            times = times.dt.tz_convert("America/New_York").dt.tz_localize(None)
    except AttributeError:
        pass
    return times


def _history_frame(today: pd.DataFrame) -> pd.DataFrame:
    raw = today.attrs.get("multi_session_bars")
    if not isinstance(raw, tuple) or not raw:
        return pd.DataFrame()
    frame = pd.DataFrame(raw, columns=("time", "open", "high", "low", "close", "volume"))
    frame["time"] = _normalized_times(frame["time"])
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna().sort_values("time").drop_duplicates("time")
    clocks = frame["time"].dt.time
    return frame.loc[(clocks >= time(9, 30)) & (clocks < time(16, 0))].reset_index(drop=True)


def _completed_today(today: pd.DataFrame, now: object | None = None) -> pd.DataFrame:
    required = {"time", "open", "high", "low", "close", "volume"}
    if today.empty or not required.issubset(today.columns):
        return pd.DataFrame()
    rows = today[list(required)].copy()
    rows["time"] = _normalized_times(rows["time"])
    rows = rows.sort_values("time").drop_duplicates("time")
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    latest_date = rows["time"].dt.date.max()
    if latest_date == cutoff.date():
        rows = rows.loc[rows["time"] < cutoff.floor("min")]
    return rows.reset_index(drop=True)


def _daily_context(history: pd.DataFrame, session_date) -> list[dict]:
    prior = history.loc[history["time"].dt.date < session_date]
    days: list[dict] = []
    for session, rows in prior.groupby(prior["time"].dt.date, sort=True):
        rows = rows.sort_values("time")
        if rows.empty:
            continue
        days.append({
            "session": session,
            "open": float(rows.iloc[0]["open"]),
            "high": float(rows["high"].max()),
            "low": float(rows["low"].min()),
            "close": float(rows.iloc[-1]["close"]),
        })
    return days


def _true_range(current: dict, previous: dict | None) -> float:
    current_range = current["high"] - current["low"]
    if previous is None:
        return current_range
    return max(
        current_range,
        abs(current["high"] - previous["close"]),
        abs(current["low"] - previous["close"]),
    )


def _orb_candidate(
    today: pd.DataFrame, *, ticker: str, strategy_id: str,
    context_gate: Callable[[list[dict]], tuple[bool, dict]],
    long_only: bool, execution_scope: str | None, now: object | None,
) -> Signal | None:
    ticker = ticker.strip().upper()
    if ticker not in _ORB_TICKERS:
        return None
    rows = _completed_today(today, now)
    history = _history_frame(today)
    if rows.empty or history.empty:
        return None
    opening = rows.loc[
        (rows["time"].dt.time >= time(9, 30))
        & (rows["time"].dt.time < time(9, 45))
    ]
    expected = [
        opening.iloc[0]["time"].replace(hour=9, minute=30, second=0, microsecond=0)
        + timedelta(minutes=index)
        for index in range(15)
    ] if not opening.empty else []
    if len(opening) != 15 or opening["time"].tolist() != expected:
        return None
    days = _daily_context(history, rows.iloc[-1]["time"].date())
    allowed, context = context_gate(days)
    if not allowed:
        return None
    or_high, or_low = float(opening["high"].max()), float(opening["low"].min())
    midpoint = (or_high + or_low) / 2.0
    for index, bar in rows.iterrows():
        clock = bar["time"].time()
        if not time(9, 45) <= clock <= time(11, 0) or index < 20:
            continue
        average_volume = float(rows.iloc[index - 20:index]["volume"].mean())
        volume_ratio = float(bar["volume"]) / average_volume if average_volume > 0 else 0.0
        if volume_ratio <= 1.5:
            continue
        direction = None
        if float(bar["close"]) > or_high:
            direction = "bullish"
        elif not long_only and float(bar["close"]) < or_low:
            direction = "bearish"
        if direction is None:
            continue
        trigger = pd.Timestamp(bar["time"]) + timedelta(minutes=1)
        key = (_execution_scope(execution_scope), ticker, strategy_id, trigger.isoformat())
        if key in _emitted:
            return None
        _emitted.add(key)
        return Signal(
            confidence=0.80, strategy_id=strategy_id, direction=direction,
            rvol=float(bar.get("rvol", 0.0) or 0.0), trigger_bar=trigger,
            meta={
                **context,
                "or_high": round(or_high, 6), "or_low": round(or_low, 6),
                "or_midpoint": round(midpoint, 6),
                "volume_ratio_20": round(volume_ratio, 6),
                "entry_timing": "completed_1m_breakout_then_next_quote",
                "exit_plan": "30% partial, 100% runner, or 1m close through opening-range midpoint",
                "observation_only": strategy_id != VWAP_DISPLACEMENT_LONG,
            },
        )
    return None


def _nr7_inside_gate(days: list[dict]) -> tuple[bool, dict]:
    if len(days) < 7:
        return False, {}
    prior = days[-1]
    prior_range = prior["high"] - prior["low"]
    nr7 = prior_range <= min(day["high"] - day["low"] for day in days[-7:]) + 1e-12
    inside = len(days) >= 2 and prior["high"] <= days[-2]["high"] and prior["low"] >= days[-2]["low"]
    return nr7 or inside, {"nr7": nr7, "inside_day": inside, "prior_range": round(prior_range, 6)}


def _atr10_gate(days: list[dict]) -> tuple[bool, dict]:
    if len(days) < 10:
        return False, {}
    prior = days[-1]
    recent = days[-10:]
    offset = len(days) - 10
    ranges = [
        _true_range(day, days[offset + index - 1] if offset + index else None)
        for index, day in enumerate(recent)
    ]
    atr10 = statistics.fmean(ranges)
    prior_range = prior["high"] - prior["low"]
    return prior_range < atr10, {"prior_range": round(prior_range, 6), "atr10": round(atr10, 6)}


def evaluate_orb_nr7_inside(today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None, now: object | None = None) -> Signal | None:
    return _orb_candidate(today, ticker=ticker, strategy_id=ORB_NR7_INSIDE, context_gate=_nr7_inside_gate, long_only=False, execution_scope=execution_scope, now=now)


def evaluate_orb_atr10(today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None, now: object | None = None) -> Signal | None:
    return _orb_candidate(today, ticker=ticker, strategy_id=ORB_ATR10_LONG, context_gate=_atr10_gate, long_only=True, execution_scope=execution_scope, now=now)


def _ema(values: Sequence[float], length: int) -> float:
    if not values:
        raise ValueError("EMA requires values")
    alpha = 2.0 / (length + 1.0)
    current = float(values[0])
    for value in values[1:]:
        current = alpha * float(value) + (1.0 - alpha) * current
    return current


def _hourly(history: pd.DataFrame, visible_at: pd.Timestamp) -> list[dict]:
    rows = history.loc[history["time"] < visible_at].copy()
    if rows.empty:
        return []
    rows["session"] = rows["time"].dt.date
    rows["minute"] = rows["time"].dt.hour * 60 + rows["time"].dt.minute - (9 * 60 + 30)
    rows = rows.loc[(rows["minute"] >= 0) & (rows["minute"] < 390)]
    rows["bucket"] = (rows["minute"] // 60).astype(int)
    output: list[dict] = []
    for (_session, bucket), group in rows.groupby(["session", "bucket"], sort=True):
        group = group.sort_values("time").drop_duplicates("time")
        offsets = group["minute"].astype(int).tolist()
        if len(offsets) < 2:
            continue
        deltas = [right - left for left, right in zip(offsets, offsets[1:]) if right > left]
        cadence = int(statistics.median(deltas)) if deltas else 0
        start = int(bucket) * 60
        expected = list(range(start, start + 60, cadence)) if cadence in {1, 5} else []
        if not expected or offsets != expected:
            continue
        output.append({
            "timestamp": pd.Timestamp(group.iloc[0]["time"]),
            "open": float(group.iloc[0]["open"]), "high": float(group["high"].max()),
            "low": float(group["low"].min()), "close": float(group.iloc[-1]["close"]),
            "volume": float(group["volume"].sum()),
        })
    return output


def _kaufman(closes: Sequence[float], periods: int = 10) -> float | None:
    if len(closes) < periods + 1:
        return None
    window = [float(value) for value in closes[-(periods + 1):]]
    path = sum(abs(right - left) for left, right in zip(window, window[1:]))
    return abs(window[-1] - window[0]) / path if path > 0 else 0.0


def _vwap_candidate(today: pd.DataFrame, *, ticker: str, strategy_id: str, execution_scope: str | None, now: object | None) -> Signal | None:
    ticker = ticker.strip().upper()
    allowed = _VWAP_KER_TICKERS if strategy_id == VWAP_KER10_LONG else _VWAP_DISPLACEMENT_TICKERS
    if ticker not in allowed:
        return None
    five = _complete_five_minute_bars(today, now=now)
    history = _history_frame(today)
    if len(five) < 2 or history.empty:
        return None
    current_date = five[-1].timestamp.date()
    session = [bar for bar in five if bar.timestamp.date() == current_date]
    price_volume = volume = 0.0
    vwaps: list[float] = []
    for bar in session:
        weight = max(float(bar.volume), 1.0)
        price_volume += ((bar.high + bar.low + bar.close) / 3.0) * weight
        volume += weight
        vwaps.append(price_volume / volume)
    displacement = False
    for index, bar in enumerate(session):
        if bar.timestamp.time() == time(10, 25):
            displacement = bar.close >= vwaps[index] * 1.01
        if index < 1 or bar.timestamp.time() < time(9, 45):
            continue
        closes = [item.close for item in session[max(0, index - 8):index + 1]]
        ema9 = _ema(closes, 9)
        previous_close, previous_vwap = session[index - 1].close, vwaps[index - 1]
        current_vwap = vwaps[index]
        touch_reclaim = previous_close > previous_vwap and bar.low <= current_vwap and bar.close > ema9
        previous_high = max(item.high for item in session[:index])
        if not touch_reclaim or previous_high <= bar.close:
            continue
        visible_at = pd.Timestamp(bar.timestamp) + timedelta(minutes=5)
        hourly = _hourly(history, visible_at)
        ker = _kaufman([item["close"] for item in hourly], 10)
        context_ok = ker is not None and ker > 0.60 if strategy_id == VWAP_KER10_LONG else displacement and bar.timestamp.time() >= time(10, 30)
        if not context_ok:
            continue
        key = (_execution_scope(execution_scope), ticker, strategy_id, visible_at.isoformat())
        if key in _emitted:
            return None
        _emitted.add(key)
        return Signal(
            confidence=0.80, strategy_id=strategy_id, direction="bullish", rvol=0.0,
            trigger_bar=visible_at,
            meta={
                "vwap": round(current_vwap, 6), "ema9": round(ema9, 6),
                "previous_high": round(previous_high, 6),
                "ker_1h_10": round(float(ker or 0.0), 6),
                "displacement_at_1030": displacement,
                "entry_timing": "completed_5m_touch_reclaim_then_next_quote",
                "exit_plan": "previous high target or first 5m close below session VWAP",
                "observation_only": strategy_id != VWAP_DISPLACEMENT_LONG,
            },
        )
    return None


def evaluate_vwap_ker(today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None, now: object | None = None) -> Signal | None:
    return _vwap_candidate(today, ticker=ticker, strategy_id=VWAP_KER10_LONG, execution_scope=execution_scope, now=now)


def evaluate_vwap_displacement(today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None, now: object | None = None) -> Signal | None:
    return _vwap_candidate(today, ticker=ticker, strategy_id=VWAP_DISPLACEMENT_LONG, execution_scope=execution_scope, now=now)


def _ema_series(values: Sequence[float], length: int) -> list[float]:
    alpha = 2.0 / (length + 1.0)
    output: list[float] = []
    current = float(values[0])
    for value in values:
        current = alpha * float(value) + (1.0 - alpha) * current
        output.append(current)
    return output


def evaluate_squeeze_macd(today: pd.DataFrame, ticker: str = "", execution_scope: str | None = None, now: object | None = None) -> Signal | None:
    ticker = ticker.strip().upper()
    if ticker not in _SQUEEZE_TICKERS:
        return None
    history = _history_frame(today)
    if history.empty:
        return None
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    hourly = _hourly(history, cutoff)
    if len(hourly) < 36:
        return None
    closes = [item["close"] for item in hourly]
    ema12, ema26 = _ema_series(closes, 12), _ema_series(closes, 26)
    macd = [fast - slow for fast, slow in zip(ema12, ema26)]
    macd_signal = _ema_series(macd, 9)
    hist = [value - signal for value, signal in zip(macd, macd_signal)]
    true_ranges: list[float] = []
    previous_close = None
    for bar in hourly:
        true_ranges.append(
            bar["high"] - bar["low"] if previous_close is None else max(
                bar["high"] - bar["low"], abs(bar["high"] - previous_close), abs(bar["low"] - previous_close),
            )
        )
        previous_close = bar["close"]
    ema20 = _ema_series(closes, 20)
    squeeze, upper, basis = [False] * len(hourly), [0.0] * len(hourly), [0.0] * len(hourly)
    for index in range(19, len(hourly)):
        window = closes[index - 19:index + 1]
        middle = statistics.fmean(window)
        deviation = math.sqrt(statistics.fmean([(value - middle) ** 2 for value in window]))
        bb_upper, bb_lower = middle + 2 * deviation, middle - 2 * deviation
        atr20 = statistics.fmean(true_ranges[index - 19:index + 1])
        kc_upper, kc_lower = ema20[index] + 1.5 * atr20, ema20[index] - 1.5 * atr20
        basis[index], upper[index] = middle, bb_upper
        squeeze[index] = bb_upper < kc_upper and bb_lower > kc_lower
    index = len(hourly) - 1
    bar = hourly[index]
    if not (squeeze[index - 1] and bar["close"] > upper[index] and hist[index] > 0 and hist[index] > hist[index - 1]):
        return None
    trigger = pd.Timestamp(bar["timestamp"]) + timedelta(minutes=60)
    key = (_execution_scope(execution_scope), ticker, SQUEEZE_MACD_LONG, trigger.isoformat())
    if key in _emitted:
        return None
    _emitted.add(key)
    return Signal(
        confidence=0.80, strategy_id=SQUEEZE_MACD_LONG, direction="bullish", rvol=0.0,
        trigger_bar=trigger,
        meta={
            "bb_length": 20, "bb_stddev": 2.0, "kc_length": 20,
            "kc_atr_multiple": 1.5, "prior_hour_squeezed": True,
            "bb_upper": round(upper[index], 6), "sma20": round(basis[index], 6),
            "macd_histogram": round(hist[index], 6),
            "prior_macd_histogram": round(hist[index - 1], 6),
            "required_dte": "3_to_5",
            "exit_plan": "150% premium target or hourly close back inside 20-SMA",
            "observation_only": True,
        },
    )


ACTIVE_OBSERVERS = (
    (ORB_NR7_INSIDE, evaluate_orb_nr7_inside),
    (ORB_ATR10_LONG, evaluate_orb_atr10),
    (VWAP_KER10_LONG, evaluate_vwap_ker),
    (VWAP_DISPLACEMENT_LONG, evaluate_vwap_displacement),
    (SQUEEZE_MACD_LONG, evaluate_squeeze_macd),
)
