"""Exact paper-execution bridge for the reviewed TSLA noise-momentum rule.

The paid study evaluated one very specific causal definition: at :00 and :30
from 10:00 through 15:30 ET, compare the completed one-minute close with a
time-of-day boundary built from the preceding *fourteen* regular sessions.
The next minute is the earliest valid entry.  This module deliberately refuses
to approximate missing one-minute history with five-minute bars or indicators.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time
from statistics import mean
from typing import Iterable, MutableMapping

import pandas as pd

from strategies.base import Signal


STRATEGY_ID = "V2_TSLA_NOISE_MOMENTUM"
TICKER = "TSLA"
PRIOR_SESSION_COUNT = 14
CHECK_MINUTES = frozenset((0, 30))
FIRST_CHECK = time(10, 0)
LAST_CHECK = time(15, 30)


def _completed_rows(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Keep only fully closed, regular-session one-minute rows before ``now``."""
    required = {"time", "open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=list(required))
    rows = frame.copy()
    rows["time"] = pd.to_datetime(rows["time"])
    # ``today_1m`` is appended after the once-per-session cached history, so
    # retain its newer copy if the broker history also contained this minute.
    rows = rows.sort_values("time").drop_duplicates("time", keep="last")
    cutoff = pd.Timestamp(now).floor("min")
    if getattr(rows["time"].dt, "tz", None) is not None:
        cutoff = cutoff.tz_localize(rows["time"].dt.tz) if cutoff.tzinfo is None else cutoff.tz_convert(rows["time"].dt.tz)
    elif cutoff.tzinfo is not None:
        cutoff = cutoff.tz_localize(None)
    rows = rows.loc[rows["time"] < cutoff]
    return rows.loc[
        (rows["time"].dt.time >= time(9, 30)) & (rows["time"].dt.time <= time(15, 59))
    ].copy()


def _sessions(rows: pd.DataFrame) -> dict[object, pd.DataFrame]:
    return {
        day: group.sort_values("time").drop_duplicates("time").reset_index(drop=True)
        for day, group in rows.groupby(rows["time"].dt.date, sort=True)
    }


def _row_at(session: pd.DataFrame, clock: time) -> pd.Series | None:
    match = session.loc[session["time"].dt.time == clock]
    return None if match.empty else match.iloc[-1]


def _open(session: pd.DataFrame) -> float | None:
    row = _row_at(session, time(9, 30))
    return None if row is None else float(row["open"])


def _prior_close(session: pd.DataFrame) -> float | None:
    row = _row_at(session, time(15, 59))
    return None if row is None else float(row["close"])


def _boundary(today: pd.DataFrame, prior: Iterable[pd.DataFrame], clock: time) -> tuple[float, float] | None:
    """Reproduce the paid-study boundary without filling or estimating gaps."""
    prior = tuple(prior)
    if len(prior) != PRIOR_SESSION_COUNT:
        return None
    today_open = _open(today)
    if today_open is None:
        return None
    moves: list[float] = []
    for session in prior:
        close_row = _row_at(session, clock)
        opening = _open(session)
        if close_row is None or opening is None:
            return None
        moves.append(abs(float(close_row["close"]) / opening - 1.0))
    previous_close = _prior_close(prior[-1])
    if previous_close is None:
        return None
    sigma = mean(moves)
    return (
        min(today_open, previous_close) * (1.0 - sigma),
        max(today_open, previous_close) * (1.0 + sigma),
    )


def _signal_at_latest_check(rows: pd.DataFrame) -> Signal | None:
    """Return a signal only when the latest completed minute is a new transition."""
    sessions = _sessions(rows)
    if not sessions:
        return None
    dates = sorted(sessions)
    today_date = dates[-1]
    if len(dates) < PRIOR_SESSION_COUNT + 1:
        return None
    today = sessions[today_date]
    prior = tuple(sessions[day] for day in dates[-(PRIOR_SESSION_COUNT + 1):-1])
    latest_time = today["time"].iloc[-1]
    active: str | None = None
    latest_signal: Signal | None = None
    for row in today.itertuples(index=False):
        clock = pd.Timestamp(row.time).time()
        if clock.minute not in CHECK_MINUTES or not FIRST_CHECK <= clock <= LAST_CHECK:
            continue
        boundary = _boundary(today, prior, clock)
        if boundary is None:
            continue
        lower, upper = boundary
        direction = "bullish" if float(row.close) > upper else "bearish" if float(row.close) < lower else None
        if direction is None:
            active = None
            continue
        if direction == active:
            continue
        active = direction
        stop = lower if direction == "bullish" else upper
        risk = abs(float(row.close) - stop)
        if risk <= 0:
            continue
        target = float(row.close) + 2 * risk if direction == "bullish" else float(row.close) - 2 * risk
        latest_signal = Signal(
            confidence=0.80,
            strategy_id=STRATEGY_ID,
            direction=direction,
            rvol=float(getattr(row, "rvol", 0.0) or 0.0),
            trigger_bar=pd.Timestamp(row.time),
            meta={
                "v2_hypothesis": "completed_1m_14_session_noise_boundary_transition",
                "validated_entry_rule": "completed_half_hour_boundary_close_then_next_minute",
                "entry_timing": "completed_1m_boundary_transition_then_next_minute",
                "noise_lower": lower,
                "noise_upper": upper,
                "prior_sessions": PRIOR_SESSION_COUNT,
                "check_clock": clock.isoformat(),
                "v2_stop": stop,
                "v2_target": target,
            },
        )
    if latest_signal is None or pd.Timestamp(latest_signal.trigger_bar) != pd.Timestamp(latest_time):
        return None
    return latest_signal


def update_noise_momentum(
    state: MutableMapping[str, object], history_1m: pd.DataFrame, today_1m: pd.DataFrame,
    *, ticker: str, now: datetime,
) -> tuple[Signal | None, str]:
    """Return the one-time exact TSLA signal, or a precise non-trading status."""
    if ticker.strip().upper() != TICKER:
        return None, "not_applicable"
    rows = _completed_rows(pd.concat([history_1m, today_1m], ignore_index=True), now)
    sessions = _sessions(rows)
    if len(sessions) < PRIOR_SESSION_COUNT + 1:
        return None, "waiting_for_14_complete_one_minute_sessions"
    signal = _signal_at_latest_check(rows)
    if signal is None:
        return None, "no_new_completed_boundary_transition"
    key = f"{ticker.upper()}:{pd.Timestamp(signal.trigger_bar).isoformat()}"
    if state.get("emitted_key") == key:
        return None, "already_emitted"
    state["emitted_key"] = key
    return signal, "completed_boundary_transition"
