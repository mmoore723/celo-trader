"""
trading/annotations/snapshot.py — clear_annotations(), snapshot_annotations().

Split out of the old single trading/annotations.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("celo_trader.annotations")


def clear_annotations(ticker: str | None = None) -> None:
    """Remove annotations for one ticker, or all tickers if ticker is None."""
    from trading.state import get_user_state  # noqa: PLC0415
    _US = get_user_state()
    if "chart_annotations" not in _US:
        return
    if ticker is None:
        _US["chart_annotations"] = {}
    else:
        _US["chart_annotations"].pop(ticker.upper(), None)


def snapshot_annotations(ticker: str, since_iso: str | None = None) -> str | None:
    """
    Return a JSON-encoded copy of this ticker's CURRENT chart annotations
    (FVG zones, BOS/TREND_CONT/ORB/AFT_REV levels, signal/veto markers) so a
    trade can carry its own "why" with it permanently — the live buffer this
    reads from is capped at 100 entries per ticker and gets overwritten as the
    session goes on, so it is NOT a substitute for saving this onto the trade
    row at entry/exit time.

    `since_iso`, if given, drops anything older than that timestamp (string
    ISO compare — annotation ts and since_iso must both be ISO datetimes,
    which they are everywhere this is called). Pass None to snapshot
    everything currently buffered for the ticker.

    Never raises: this is called from the live entry/exit path, and a bad
    snapshot must never block recording an actual trade. Any failure logs a
    warning and returns None (trade write proceeds with no annotations).
    """
    import json as _json
    try:
        from trading.state import get_user_state  # noqa: PLC0415
        _US = get_user_state()
        bucket = _US.get("chart_annotations", {}).get(ticker.upper(), [])
        if since_iso:
            bucket = [a for a in bucket if a.get("ts", "") >= since_iso]
        if not bucket:
            return None
        return _json.dumps(bucket)
    except Exception:
        logger.warning(
            "snapshot_annotations failed for %s — trade will save with no annotations", ticker, exc_info=True,
        )
        return None
