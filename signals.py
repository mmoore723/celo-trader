"""
signals.py — Pure ORB Signal Engine.

ALL secondary indicator logic (RSI, MACD, Bollinger Bands, ADX, candlestick
patterns, multi-timeframe aggregation) has been removed.  The live trading
pipeline is 100% Price + Volume + VWAP.

ORB Signal Logic:
  1. Opening range  = first 5-minute candle of the session (09:30–09:35 ET)
  2. Breakout gate  = subsequent candle closes OUTSIDE the OR High/Low
  3. Volume gate    = breakout candle RVOL ≥ 200% of the 10-day same-slot avg
  4. VWAP gate      = price above VWAP for calls, below VWAP for puts

Returns:
  detect_orb_breakout() → Optional[tuple[str, float]]
    ("bullish" | "bearish",  rvol_of_breakout_candle)  |  None

The RVOL value is passed to risk.evaluate_rr() and logged as
Entry_Volume_Multiplier on every trade_opened event.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("celo_trader.signals")


# ── Data helpers ──────────────────────────────────────────────────────────────

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
    return df.sort_values("time").reset_index(drop=True)


# ── Volume helpers ────────────────────────────────────────────────────────────

def is_volume_sufficient(df: pd.DataFrame) -> bool:
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


# ── Earnings filter ───────────────────────────────────────────────────────────

def is_near_earnings(earnings_dates: list[str], blackout_days: int = 2) -> bool:
    """Return True if any earnings date falls within blackout_days of today."""
    from datetime import date
    today = date.today()
    for ed in earnings_dates:
        try:
            if abs((date.fromisoformat(ed) - today).days) <= blackout_days:
                logger.info("Earnings blackout: %s", ed)
                return True
        except ValueError:
            continue
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ORB (Opening Range Breakout) Engine — the ONLY live signal source
# ═══════════════════════════════════════════════════════════════════════════════

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


def compute_rvol(df: pd.DataFrame, lookback_days: int = 10) -> pd.Series:
    """
    Bar-level Relative Volume (RVOL): ratio of current bar volume to the
    average volume of that same time-of-day bar over the past 10 trading days.

    RVOL ≥ 2.0 → the candle has 200% of the historical average for that slot.
    This is the institutional volume gate for ORB entry.

    Falls back to 20-bar rolling average if fewer than 2 sessions of history.
    """
    if df.empty:
        return pd.Series(dtype=float)

    df = df.copy()
    df["_date"] = df["time"].dt.date
    df["_tod"]  = df["time"].dt.hour * 60 + df["time"].dt.minute

    unique_days = sorted(df["_date"].unique())
    if len(unique_days) < 2:
        # Not enough cross-day history — fall back to rolling mean
        rolling_avg = df["volume"].rolling(20, min_periods=1).mean().shift(1)
        rvol = df["volume"] / rolling_avg.replace(0, np.nan)
        return rvol.rename("rvol")

    # Build time-of-day volume lookup from prior sessions only
    tod_vols: dict[int, list[float]] = {}
    for d in unique_days[:-1]:       # exclude the current (most recent) day
        day_df = df[df["_date"] == d]
        for _, row in day_df.iterrows():
            tod_vols.setdefault(int(row["_tod"]), []).append(float(row["volume"]))

    def _avg_for_tod(tod: int) -> float:
        vols = tod_vols.get(tod, [])
        tail = vols[-lookback_days:]     # cap at lookback_days (default 10)
        return float(np.mean(tail)) if tail else np.nan

    avg_series = df["_tod"].apply(_avg_for_tod)
    rvol = df["volume"] / avg_series.replace(0, np.nan)
    return rvol.rename("rvol")


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) over `period` bars.
    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    Used by the chart API to surface volatility context.
    """
    if df.empty or len(df) < 2:
        return pd.Series([np.nan] * len(df), index=df.index, name="atr")
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().rename("atr")


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
    below for the gate constant used throughout this module.

    Returns None if the 09:30 bar is absent entirely.
    If only 1 or 2 bars are present (bot started mid-range), the range
    is computed from whatever bars exist and a warning is logged.
    """
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


# ── ORB breakout detection ────────────────────────────────────────────────────

# Earliest bar that can trigger an ORB breakout signal.
# The 15-minute opening range spans 09:30, 09:35, and 09:40.
# The range is complete only after the 09:40 bar closes, so the FIRST
# valid breakout bar is 09:45 (minutes-since-midnight = 585).
ORB_SIGNAL_MIN: int = 9 * 60 + 45   # 585 — signals blocked before this

try:
    from config import VOLUME_FILTER_MULTIPLIER as _CFG_RVOL
    ORB_RVOL_THRESHOLD: float = float(_CFG_RVOL)   # reads config.py (default 1.2)
except Exception:
    ORB_RVOL_THRESHOLD: float = 1.2                 # fallback if config unavailable


def detect_orb_breakout(df: pd.DataFrame) -> Optional[tuple[str, float]]:
    """
    Core ORB signal — called once per tick by trading_logic._tick().

    Returns (direction, rvol) or None.
      direction : "bullish" | "bearish"
      rvol      : Entry_Volume_Multiplier of the breakout candle (used in audit log)

    Logic:
    1. Find the Opening Range (09:30 bar).
    2. Walk subsequent bars looking for a candle that closes outside OR High/Low.
    3. Gate 1 — RVOL: breakout candle volume ≥ 200% of 10-day same-slot average.
    4. Gate 2 — VWAP: bullish requires close > VWAP; bearish requires close < VWAP.
    5. Signal fires on the FIRST qualifying breakout bar of the session.

    df must contain today's 5-min bars sorted ascending.
    If df spans multiple sessions the function operates on the most recent day.
    """
    if df.empty or len(df) < 2:
        return None

    # Isolate today's bars
    latest_date = df["time"].dt.date.max()
    today_df    = df[df["time"].dt.date == latest_date].reset_index(drop=True)

    if len(today_df) < 2:
        return None

    or_info = get_opening_range(today_df)
    if or_info is None:
        return None

    or_high = or_info["high"]
    or_low  = or_info["low"]

    # Compute VWAP and RVOL (pass full df so prior days inform RVOL calc)
    vwap_series = compute_vwap(today_df)
    rvol_series = compute_rvol(df, lookback_days=10)
    rvol_today  = rvol_series.reindex(today_df.index)

    for idx in range(1, len(today_df)):
        bar     = today_df.iloc[idx]
        bar_min = bar["time"].hour * 60 + bar["time"].minute

        # ── 15-min range guard: do not fire before 09:45 ─────────────────────
        # The OR spans 09:30, 09:35, and 09:40. Signals from any bar inside
        # that window would be measuring a breakout against an incomplete range.
        if bar_min < ORB_SIGNAL_MIN:
            continue

        close = float(bar["close"])
        vwap  = float(vwap_series.iloc[idx]) if not pd.isna(vwap_series.iloc[idx]) else None
        rvol  = float(rvol_today.iloc[idx])  if not pd.isna(rvol_today.iloc[idx])  else 0.0

        # ── Breakout direction ────────────────────────────────────────────────
        if close > or_high:
            direction = "bullish"
        elif close < or_low:
            direction = "bearish"
        else:
            continue

        # ── Gate 1: Volume ≥ 200% of 10-day average ──────────────────────────
        if rvol < ORB_RVOL_THRESHOLD:
            logger.debug(
                "ORB %s rejected — RVOL %.2f < %.1f at %s",
                direction, rvol, ORB_RVOL_THRESHOLD, bar["time"],
            )
            continue   # next bar may re-confirm with volume

        # ── Gate 2: VWAP direction alignment ─────────────────────────────────
        if vwap is not None:
            if direction == "bullish" and close <= vwap:
                logger.debug(
                    "ORB bullish rejected — close %.4f ≤ VWAP %.4f at %s",
                    close, vwap, bar["time"],
                )
                continue
            if direction == "bearish" and close >= vwap:
                logger.debug(
                    "ORB bearish rejected — close %.4f ≥ VWAP %.4f at %s",
                    close, vwap, bar["time"],
                )
                continue

        logger.info(
            "ORB signal: %s | OR=[%.4f, %.4f] close=%.4f RVOL=%.2fx VWAP=%s bar=%s",
            direction, or_low, or_high, close, rvol,
            f"{vwap:.4f}" if vwap else "n/a", bar["time"],
        )
        return direction, rvol   # (direction, Entry_Volume_Multiplier)

    return None
