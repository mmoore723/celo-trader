"""
strategy_router/indicator_frame.py — _build_indicator_frame(): computes all
indicators shared by the strategy modules in a single pass.

Split out of the old single strategy_router.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import pandas as pd

from signals import compute_vwap_bands, compute_rvol


def _build_indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all indicators shared by the strategy modules in a single pass.
    Returns an augmented DataFrame containing only today's bars.

    Columns added:
      vwap, vwap_upper1, vwap_lower1, vwap_upper2, vwap_lower2
      rvol       — 10-day true RVOL (falls back to 20-bar rolling proxy)
      ema50      — long-term trend filter
      atr        — 14-bar ATR for gap sizing + MFE gates
      vol_sma20  — 100-bar volume rolling mean (intraday reference)
      session_gap_pct — today's open vs. prior session's close, as a % —
                  added 2026-07-23 for strategies/gap_go.py (Gap 2, professional-
                  strategy-alignment audit). Constant-broadcast across every row
                  of today, same pattern as any other single-value-per-day field
                  strategies need — evaluate() only ever sees `today`, never the
                  full multi-day df, so this is computed once here where prior-day
                  data is still available, not inside the strategy itself.
    """
    if df.empty:
        return df

    latest_date = df["time"].dt.date.max()
    # BUG FIX 2026-07-22: capture today's row labels BEFORE reset_index below.
    # rvol_series (computed a few lines down) is indexed on the FULL
    # multi-day df. Previously `today` was reset to a 0-based index first,
    # then reindexed against that reset index — silently pulling whichever
    # earlier day happened to start at the same row offset instead of
    # today's real RVOL, any time df spans more than one day. Confirmed via
    # a direct call to this function on synthetic multi-day data. Affects
    # both the backtester and live (trading/entry.py's df5 is multi-day
    # after the RVOL history augment).
    today_idx   = df.index[df["time"].dt.date == latest_date]
    today       = df[df["time"].dt.date == latest_date].copy().reset_index(drop=True)

    _vwap_frame           = compute_vwap_bands(today, num_stds=(1, 2))
    today["vwap"]         = _vwap_frame["vwap"].ffill()
    today["vwap_upper1"]  = _vwap_frame["vwap_upper1"].ffill()
    today["vwap_lower1"]  = _vwap_frame["vwap_lower1"].ffill()
    today["vwap_upper2"]  = _vwap_frame["vwap_upper2"].ffill()
    today["vwap_lower2"]  = _vwap_frame["vwap_lower2"].ffill()

    rvol_series   = compute_rvol(df, lookback_days=10)
    # Positional assign via .to_numpy() — sidesteps index alignment entirely.
    # today_idx and today are in the same row order (both derived from the
    # same boolean mask, mask application preserves order), so this is safe.
    today["rvol"] = rvol_series.reindex(today_idx).fillna(1.0).to_numpy()

    today["ema50"] = today["close"].ewm(span=50, adjust=False).mean()

    hl  = today["high"]  - today["low"]
    hcp = (today["high"]  - today["close"].shift(1)).abs()
    lcp = (today["low"]   - today["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    today["atr"] = tr.ewm(span=14, adjust=False).mean()

    today["vol_sma20"] = today["volume"].rolling(100, min_periods=20).mean()

    # ── Session gap % (constant-broadcast) ────────────────────────────────
    _prior_mask = df["time"].dt.date < latest_date
    if _prior_mask.any() and len(today) > 0:
        _prior_close = float(df.loc[_prior_mask].iloc[-1]["close"])
        _today_open  = float(today.iloc[0]["open"])
        today["session_gap_pct"] = ((_today_open - _prior_close) / _prior_close * 100.0
                                     if _prior_close else 0.0)
    else:
        today["session_gap_pct"] = 0.0   # no prior-day data (e.g. synthetic/short backtest window)

    return today
