"""
scanner/helpers.py — Small shared helpers: ET "now", hour/minute window
check, and the intraday ATR computation used by the Phase-2 rescore.

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from datetime import datetime

def _et_now() -> datetime:
    """Return naive New York wall time, including daylight-saving transitions."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)


def _hm_in_range(hour: int, minute: int,
                 start: tuple[int, int], end: tuple[int, int]) -> bool:
    val = hour * 60 + minute
    lo  = start[0] * 60 + start[1]
    hi  = end[0]   * 60 + end[1]
    return lo <= val <= hi


def _compute_atr(bars: list[dict]) -> tuple[float, float]:
    """
    Return (atr_dollars, atr_pct) for the last 14 bars.
    atr_pct = atr_dollars / last_close.
    Returns (0.0, 0.0) if bars insufficient.
    """
    if len(bars) < 2:
        return 0.0, 0.0
    trs = []
    for i in range(1, len(bars)):
        h  = float(bars[i].get("h", 0))
        l  = float(bars[i].get("l", 0))
        pc = float(bars[i - 1].get("c", bars[i].get("c", 0)))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_dollars = sum(trs[-14:]) / min(len(trs), 14)
    last_close  = float(bars[-1].get("c", 0))
    atr_pct     = atr_dollars / last_close if last_close > 0 else 0.0
    return round(atr_dollars, 4), round(atr_pct, 6)

