"""
signals/data_helpers.py — bars_to_df(): convert Alpaca v2 OHLCV dicts to a
sorted, ET-wall-clock DataFrame.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import pandas as pd


def bars_to_df(bars: list[dict]) -> pd.DataFrame:
    """
    Convert a list of OHLCV dicts (Alpaca v2 format) to a sorted DataFrame.

    CRITICAL: Alpaca bar timestamps are UTC strings (e.g. "2024-01-15T14:30:00Z").
    All downstream intraday checks use wall-clock ET time:
      • get_opening_range()  → hour == 9 and minute == 30
      • _eval_inst_orb()     → bar_min > 11 * 60
      • _eval_vwap_pullback()→ bar_min < 9 * 60 + 45
    Without the conversion, 9:30 ET = 14:30 UTC gives bar_min = 870 which is
    > 660 (11 h), so the ORB loop breaks immediately — zero trades fire.
    """
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df = df.rename(columns={"t": "time", "o": "open", "h": "high",
                             "l": "low",  "c": "close", "v": "volume"})
    # Parse as UTC then convert to ET wall-clock time (handles EST/EDT automatically).
    # Strip timezone info afterwards so the rest of the pipeline stays tz-naive.
    try:
        df["time"] = (
            pd.to_datetime(df["time"], utc=True)
            .dt.tz_convert("America/New_York")
            .dt.tz_localize(None)
        )
    except Exception:
        # Fallback for tz-naive or already-local timestamps
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    result = df.sort_values("time").reset_index(drop=True)
    if any("data_feed" in row for row in bars):
        from broker.shared_market import bar_provenance
        result.attrs.update(bar_provenance(bars))
        result.attrs['source'] = result.attrs['data_feed']
    return result
