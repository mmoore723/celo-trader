"""
signals/rvol.py — compute_rvol(): bar-level Relative Volume against the
same time-of-day slot over prior sessions.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import numpy as np
import pandas as pd


def compute_rvol(df: pd.DataFrame, lookback_days: int = 10) -> pd.Series:
    """
    Bar-level Relative Volume (RVOL): ratio of current bar volume to the
    average volume of that same time-of-day slot over the past 10 trading
    days.

    RVOL ≥ 2.0 → the candle has 200% of the historical average for that slot.
    This is the institutional volume gate for ORB entry.

    Falls back to 20-bar rolling average if fewer than 2 sessions of history.

    FIX 2026-07-28: the live pipeline feeds this a MIXED-resolution df —
    today's bars are 1-minute (trading/entry.py switched to 1Min so
    strategies react on the exact breakout candle), but the ~15-day
    historical baseline is 5-minute (Alpaca free-tier can't pull 15 days of
    1-min history). The old version matched by EXACT minute-of-day, so
    ~80% of today's 1-min bars (anything not on a :00/:05/:10... mark)
    found no historical match at all → NaN → displayed/scored as 0.0×, and
    even the 20% that DID match were comparing one minute's volume against
    a five-minute historical average — deflating RVOL ~5x. Confirmed live
    via scripts/diagnostics/diag_rvol_live_check.py: RVOL was reading 0.0×
    on nearly every bar, every ticker, all day.
    Now: bucket ALL rows (history and today alike) into 5-minute slots —
    history rows are already one-per-bucket; today's finer 1-min rows get
    summed cumulatively WITHIN their current (possibly still-forming)
    bucket, so the comparison is apples-to-apples bucket volume vs. bucket
    volume. Early minutes of a forming bucket will read a bit low relative
    to the full historical bucket average (partial vs. complete) — that's
    an inherent, honest tradeoff of updating every minute instead of only
    at bucket close, not a bug.
    """
    if df.empty:
        return pd.Series(dtype=float)

    df = df.copy()
    df["_date"] = df["time"].dt.date
    df["_tod"]  = df["time"].dt.hour * 60 + df["time"].dt.minute
    df["_tod5"] = (df["_tod"] // 5) * 5   # 5-minute bucket key — see FIX note above

    unique_days = sorted(df["_date"].unique())
    if len(unique_days) < 2:
        # Not enough cross-day history — fall back to rolling mean
        rolling_avg = df["volume"].rolling(20, min_periods=1).mean().shift(1)
        rvol = df["volume"] / rolling_avg.replace(0, np.nan)
        return rvol.rename("rvol")

    latest_day = unique_days[-1]

    # Build 5-min-bucket volume lookup from prior sessions only. groupby+sum
    # handles both cases correctly: if a prior day's rows are already 5-min
    # bars (one row per bucket), sum is a no-op; if any prior day happens to
    # be finer-grained, it gets correctly rolled up too.
    hist_df = df[df["_date"] != latest_day]
    hist_bucket_vol = (
        hist_df.groupby(["_date", "_tod5"])["volume"].sum().reset_index()
    )
    tod_vols: dict[int, list[float]] = {}
    for _, row in hist_bucket_vol.iterrows():
        tod_vols.setdefault(int(row["_tod5"]), []).append(float(row["volume"]))

    # FIX 2026-07-31 (backtest performance): this used to be df["_tod5"].
    # apply(_avg_for_tod5) — calling a Python function once per ROW (up to
    # thousands, since route_signals() calls compute_rvol() fresh every
    # single tick per backtester.py's ENTRY_LOOKBACK_DAYS comment above).
    # But the result only depends on _tod5, which has ~78 distinct values
    # in a trading day — the exact same value gets recomputed over and over
    # for every row sharing a bucket. Confirmed via py-spy profiling a real
    # backtest run: this was 24% of all CPU time. Precomputing the ~78
    # possible outputs once, then using a vectorized dict .map() (a single
    # compiled hash-lookup pass) instead of .apply() (n Python calls),
    # keeps the identical per-bucket averaging logic and NaN-for-missing
    # fallback, just computed once per bucket instead of once per row.
    _unique_tod5 = tod_vols.keys()
    _avg_by_tod5 = {
        _t: (float(np.mean(_v[-lookback_days:])) if _v else np.nan)
        for _t, _v in tod_vols.items()
    }
    avg_series = df["_tod5"].map(_avg_by_tod5)

    # Today's volume-so-far WITHIN its current 5-min bucket (cumulative sum
    # resets at each new bucket) — compared against the historical FULL-
    # bucket average. Non-today rows keep their raw per-row volume, matching
    # prior behavior for any caller that reads rvol on historical rows too.
    today_mask = df["_date"] == latest_day
    cum_bucket_vol = df.groupby(["_date", "_tod5"])["volume"].cumsum()
    numerator = df["volume"].where(~today_mask, cum_bucket_vol)

    rvol = numerator / avg_series.replace(0, np.nan)
    return rvol.rename("rvol")
