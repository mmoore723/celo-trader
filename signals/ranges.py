"""
signals/ranges.py — get_opening_range() for the 15-minute ORB range.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from typing import Optional

import pandas as pd


def get_opening_range(df: pd.DataFrame) -> Optional[dict]:
    """
    Return the Opening Range (OR) — the first 15 minutes of the session,
    spanning three 5-minute bars: 09:30, 09:35, and 09:40.

    OR high  = highest high  across all three bars
    OR low   = lowest  low   across all three bars
    OR open  = open of the 09:30 bar
    OR close = close of the last available OR bar (09:40 if present)
    OR volume= sum of volume across all three bars

    Callers must NOT fire a breakout signal until 09:45 — the range is
    not complete until the 09:40 bar has closed.  See ``ORB_SIGNAL_MIN``
    (signals/orb_breakout.py) for the gate constant used throughout this
    module.

    Returns None if the 09:30 bar is absent entirely.
    If only 1 or 2 bars are present (bot started mid-range), the range
    is computed from whatever bars exist and a warning is logged.
    """
    import logging
    logger = logging.getLogger("celo_trader.signals")

    if df.empty:
        return None

    # Collect the three OR bars: 9:30, 9:35, 9:40
    _or_slots = {(9, 30), (9, 35), (9, 40)}
    or_mask   = df["time"].apply(lambda t: (t.hour, t.minute) in _or_slots)
    or_bars   = df[or_mask].reset_index(drop=True)

    if or_bars.empty:
        logger.debug("Opening range bars (09:30–09:40) not found")
        return None

    n = len(or_bars)
    if n < 3:
        logger.warning(
            "Opening range incomplete: only %d/3 bars present "
            "(bot may have started mid-range). Using partial range.", n,
        )

    return {
        "high":   float(or_bars["high"].max()),
        "low":    float(or_bars["low"].min()),
        "open":   float(or_bars.iloc[0]["open"]),
        "close":  float(or_bars.iloc[-1]["close"]),
        "volume": float(or_bars["volume"].sum()),
        "time":   or_bars.iloc[0]["time"],
        "bars":   n,   # 1–3; callers can check completeness
    }
