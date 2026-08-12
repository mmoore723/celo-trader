"""Causal SPY intraday noise-boundary momentum signals.

This is a research translation of the predeclared *noise area* concept: at a
given minute, compare today's move from its open to the average absolute move
at that same minute over the previous sessions.  A position is considered only
when price is outside that time-varying zone.  It deliberately has no broker,
order, or option-price dependency.

The function below uses only completed one-minute bars.  A signal timestamp is
the opening time of the minute whose close established the condition; callers
must therefore fill no earlier than the following minute.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, time
from statistics import mean
from typing import Iterable, Mapping, Sequence

from research.engine.models import Bar, Side, Signal


STRATEGY_ID = "V2_SPY_NOISE_MOMENTUM"
_CHECK_MINUTES = frozenset((0, 30))
_FIRST_CHECK = time(10, 0)
_LAST_CHECK = time(15, 30)


def _sessions(bars: Iterable[Bar]) -> dict[date, tuple[Bar, ...]]:
    grouped: dict[date, list[Bar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.timestamp.date()].append(bar)
    return {
        day: tuple(sorted(session, key=lambda item: item.timestamp))
        for day, session in grouped.items()
    }


def _close_by_clock(bars: Sequence[Bar]) -> dict[time, float]:
    return {bar.timestamp.time(): bar.close for bar in bars}


def _session_open(bars: Sequence[Bar]) -> float | None:
    first = next((bar for bar in bars if bar.timestamp.time() == time(9, 30)), None)
    return first.open if first is not None else None


def _prior_regular_close(bars: Sequence[Bar]) -> float | None:
    close_bar = next((bar for bar in reversed(bars) if bar.timestamp.time() == time(15, 59)), None)
    return close_bar.close if close_bar is not None else None


def noise_boundaries(
    session: Sequence[Bar], prior_sessions: Sequence[Sequence[Bar]], clock: time,
) -> tuple[float, float] | None:
    """Return today's adjusted lower/upper noise boundary at ``clock``.

    The previous sessions must be strictly earlier and are consumed as-is.  A
    missing open/close at a clock time makes the boundary unavailable instead
    of silently estimating it.
    """
    if len(prior_sessions) != 14:
        return None
    today_open = _session_open(session)
    if today_open is None:
        return None
    prior_closes = [_close_by_clock(previous).get(clock) for previous in prior_sessions]
    prior_opens = [_session_open(previous) for previous in prior_sessions]
    if any(value is None for value in (*prior_closes, *prior_opens)):
        return None
    moves = [abs(float(close) / float(open) - 1.0) for close, open in zip(prior_closes, prior_opens)]
    previous_close = _prior_regular_close(prior_sessions[-1])
    if previous_close is None:
        return None
    sigma = mean(moves)
    upper_anchor = max(today_open, previous_close)
    lower_anchor = min(today_open, previous_close)
    return lower_anchor * (1.0 - sigma), upper_anchor * (1.0 + sigma)


def noise_momentum_signals(bars: Iterable[Bar]) -> tuple[Signal, ...]:
    """Emit transitions outside the 14-session adaptive SPY noise area.

    The strategy checks completed one-minute candles at :00 and :30 from
    10:00 through 15:30.  It emits only when the state changes (flat -> long,
    flat -> short, or reversal), so a sustained trend does not manufacture a
    new trade every thirty minutes.  Returning inside the zone resets the
    state; the exit is tested separately by the causal VWAP/boundary plan.
    """
    sessions = _sessions(bars)
    dates = sorted(sessions)
    signals: list[Signal] = []
    for index, day in enumerate(dates):
        if index < 14:
            continue
        session = sessions[day]
        by_clock = {bar.timestamp.time(): bar for bar in session}
        prior = tuple(sessions[prior_day] for prior_day in dates[index - 14:index])
        active: Side | None = None
        for bar in session:
            clock = bar.timestamp.time()
            if (clock.minute not in _CHECK_MINUTES or clock < _FIRST_CHECK or clock > _LAST_CHECK
                    or clock.second or clock.microsecond):
                continue
            boundaries = noise_boundaries(session, prior, clock)
            if boundaries is None:
                continue
            lower, upper = boundaries
            candidate = Side.LONG if bar.close > upper else Side.SHORT if bar.close < lower else None
            if candidate is None:
                active = None
                continue
            if candidate is active:
                continue
            # A signal needs a structural stop/target to satisfy the neutral
            # V2 domain contract.  The actual research exit is the separately
            # planned adaptive band/VWAP exit, not this placeholder target.
            entry = bar.close
            if candidate is Side.LONG:
                stop, target = lower, max(entry * 1.001, entry + (entry - lower))
            else:
                stop, target = upper, min(entry * .999, entry - (upper - entry))
            if not (stop < entry < target if candidate is Side.LONG else target < entry < stop):
                continue
            signals.append(Signal(
                STRATEGY_ID, candidate, bar.timestamp, entry, stop, target,
                {"noise_lower": lower, "noise_upper": upper, "noise_sigma": (upper / max(_session_open(session) or upper, _prior_regular_close(prior[-1]) or upper)) - 1.0,
                 "check_clock": clock.isoformat(), "prior_sessions": 14},
            ))
            active = candidate
    return tuple(signals)


def boundaries_by_timestamp(bars: Iterable[Bar]) -> Mapping[object, tuple[float, float]]:
    """Expose only causal boundaries for the exit planner and visualization."""
    sessions = _sessions(bars)
    dates = sorted(sessions)
    output: dict[object, tuple[float, float]] = {}
    for index, day in enumerate(dates):
        if index < 14:
            continue
        session, prior = sessions[day], tuple(sessions[item] for item in dates[index - 14:index])
        for bar in session:
            boundary = noise_boundaries(session, prior, bar.timestamp.time())
            if boundary is not None:
                output[bar.timestamp] = boundary
    return output
