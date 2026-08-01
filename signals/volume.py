"""
signals/volume.py — Generic volume-sufficiency check and RVOL-based ticker
ranking.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging

from signals.data_helpers import bars_to_df

logger = logging.getLogger("celo_trader.signals")


def is_volume_sufficient(df) -> bool:
    """
    Generic volume check used by the scanner and pre-entry guard.
    Reads volume_filter_enabled and volume_filter_multiplier from live settings.
    If the filter is toggled off in Risk Settings, always returns True.
    """
    try:
        from config import get_settings, VOLUME_FILTER_MULTIPLIER
        s = get_settings()
        if not s.get("volume_filter_enabled", True):
            return True
        multiplier = float(s.get("volume_filter_multiplier", VOLUME_FILTER_MULTIPLIER))
    except Exception:
        multiplier = 2.0

    if len(df) < 20:
        return True
    avg_vol  = df["volume"].iloc[-20:].mean()
    last_vol = df["volume"].iloc[-1]
    ok = last_vol >= avg_vol * multiplier
    if not ok:
        logger.debug("Volume low: %.0f vs avg %.0f (need %.1fx)", last_vol, avg_vol, multiplier)
    return ok


def relative_volume_rank(bars_by_ticker: dict[str, list[dict]]) -> list[str]:
    """
    Rank tickers by RVOL (current bar / 20-bar rolling average).
    Used by the pre-market scanner for watchlist building.
    """
    scores = {}
    for ticker, bars in bars_by_ticker.items():
        df = bars_to_df(bars)
        if df.empty or len(df) < 20:
            scores[ticker] = 0.0
            continue
        avg_vol = df["volume"].iloc[-20:-1].mean()
        scores[ticker] = df["volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0.0
    return sorted(scores, key=scores.get, reverse=True)
