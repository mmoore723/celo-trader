"""Causal structural exit for the reviewed VWAP 10:30 paper strategy."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import json
from typing import Mapping

import pandas as pd


VWAP_DISPLACEMENT_STRATEGY_ID = "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG"
FALLBACK_HOLD_MINUTES = 90


def _naive_et(value: object) -> pd.Timestamp | None:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("America/New_York").tz_localize(None)
    return stamp


def _completed_bars(
    frame: pd.DataFrame | None, *, now: pd.Timestamp, minutes: int,
) -> pd.DataFrame:
    required = {"time", "high", "low", "close", "volume"}
    if frame is None or frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    rows = frame[list(required)].copy()
    rows["time"] = pd.to_datetime(rows["time"], errors="coerce")
    try:
        if rows["time"].dt.tz is not None:
            rows["time"] = rows["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    except AttributeError:
        return pd.DataFrame()
    for column in ("high", "low", "close", "volume"):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows = rows.dropna().sort_values("time").drop_duplicates("time", keep="last")
    clocks = rows["time"].dt.time
    rows = rows.loc[
        (rows["time"].dt.date == now.date())
        & (clocks >= time(9, 30))
        & (clocks < time(16, 0))
        & (rows["time"] + pd.Timedelta(minutes=minutes) <= now)
    ].copy()
    rows["visible_at"] = rows["time"] + pd.Timedelta(minutes=minutes)
    return rows.reset_index(drop=True)


def _context(raw: object) -> dict[str, object]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def evaluate_vwap_displacement_exit(
    entry_time: datetime | str | None,
    now: datetime,
    *,
    one_minute_bars: pd.DataFrame | None,
    five_minute_bars: pd.DataFrame | None,
    strategy_context: object,
) -> tuple[bool, str]:
    """Return the first decision visible after the confirmed entry.

    The target is frozen at signal time. The VWAP stop is recomputed only from
    completed regular-session five-minute bars. An unavailable target or bar
    feed cannot create a synthetic structural decision; the reviewed 90-minute
    hold remains a fail-safe, and 15:55 ET is always the final cap.
    """
    entry = _naive_et(entry_time)
    current = _naive_et(now)
    if entry is None or current is None:
        return True, "vwap_displacement_missing_entry_time_safety"

    cap = current.replace(hour=15, minute=55, second=0, microsecond=0)
    decision_cutoff = min(current, cap)
    context = _context(strategy_context)
    target = _positive_number(context.get("previous_high"))
    choices: list[tuple[pd.Timestamp, str]] = []

    one = _completed_bars(one_minute_bars, now=decision_cutoff, minutes=1)
    if target is not None and not one.empty:
        # Match research: the fill-minute high may predate the purchase.
        reached = one.loc[(one["time"] > entry.floor("min")) & (one["high"] >= target)]
        if not reached.empty:
            choices.append((pd.Timestamp(reached.iloc[0]["visible_at"]), "vwap_displacement_prior_high_target"))

    five = _completed_bars(five_minute_bars, now=decision_cutoff, minutes=5)
    if not five.empty:
        weights = five["volume"].clip(lower=1.0)
        typical = (five["high"] + five["low"] + five["close"]) / 3.0
        five["session_vwap"] = (typical * weights).cumsum() / weights.cumsum()
        failed = five.loc[
            (five["visible_at"] > entry)
            & (five["close"] < five["session_vwap"])
        ]
        if not failed.empty:
            choices.append((pd.Timestamp(failed.iloc[0]["visible_at"]), "vwap_displacement_5m_close_below_vwap"))

    if choices:
        _when, reason = min(choices, key=lambda item: item[0])
        return True, reason
    if current >= cap:
        return True, "vwap_displacement_eod_1555"
    if current - entry >= timedelta(minutes=FALLBACK_HOLD_MINUTES) and (
        target is None or one.empty or five.empty
    ):
        return True, "vwap_displacement_missing_structure_90m_safety"
    return False, "hold"
