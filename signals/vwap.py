"""
signals/vwap.py — Intraday anchored VWAP and volume-weighted sigma bands.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import numpy as np
import pandas as pd


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Intraday anchored VWAP — resets at the start of each calendar day.

    Formula: cumulative(typical_price × volume) / cumulative(volume)
    Typical price = (high + low + close) / 3

    Returns a Series aligned to df.index.  NaN for bars with zero volume.
    """
    df = df.copy()
    df["_date"] = df["time"].dt.date
    df["_tp"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["_tpv"]  = df["_tp"] * df["volume"]

    df["_cum_tpv"] = df.groupby("_date")["_tpv"].cumsum()
    df["_cum_vol"] = df.groupby("_date")["volume"].cumsum()

    vwap = df["_cum_tpv"] / df["_cum_vol"].replace(0, np.nan)
    return vwap.rename("vwap")


def compute_vwap_bands(
    df: pd.DataFrame,
    num_stds: tuple = (1, 2),
) -> pd.DataFrame:
    """
    Compute anchored VWAP with volume-weighted standard deviation bands.

    Uses the same intraday-anchored formula as compute_vwap() but also
    accumulates a volume-weighted variance to derive σ (sigma) bands:

        σ² = Σ(vol × (tp - vwap)²) / Σ(vol)     (intraday cumulative, resets daily)
        σ  = sqrt(σ²)

    Returns a DataFrame with columns:
        vwap, vwap_upper1, vwap_lower1, vwap_upper2, vwap_lower2

    These are plotted on the live chart as transparent bands so the trader
    can see where institutional buyers/sellers are likely positioned relative
    to the day's average price.
    """
    if df.empty:
        cols = (["vwap"]
                + [f"vwap_upper{n}" for n in num_stds]
                + [f"vwap_lower{n}" for n in num_stds])
        return pd.DataFrame(columns=cols, index=df.index, dtype=float)

    df = df.copy()
    df["_date"] = df["time"].dt.date
    df["_tp"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["_tpv"]  = df["_tp"] * df["volume"]

    df["_cum_tpv"] = df.groupby("_date")["_tpv"].cumsum()
    df["_cum_vol"] = df.groupby("_date")["volume"].cumsum()

    vwap = df["_cum_tpv"] / df["_cum_vol"].replace(0, np.nan)

    # Volume-weighted variance: Σ(vol × (tp - vwap)²) / Σ(vol)
    df["_sq_dev"]     = (df["_tp"] - vwap) ** 2 * df["volume"]
    df["_cum_sq_dev"] = df.groupby("_date")["_sq_dev"].cumsum()
    std_dev = np.sqrt(df["_cum_sq_dev"] / df["_cum_vol"].replace(0, np.nan))

    result = pd.DataFrame({"vwap": vwap}, index=df.index)
    for n in num_stds:
        result[f"vwap_upper{n}"] = vwap + n * std_dev
        result[f"vwap_lower{n}"] = vwap - n * std_dev

    return result
