"""
regime_manager/adx.py — ADX(14) trend-STRENGTH gate (moved from
strategy_router.py 2026-07-16).

Breakout/continuation strategies need a TRENDING regime to work. ADX(14) on
5-min bars below 25 = mean-reverting chop — raw breakouts get stopped out
repeatedly in that regime. This is trend STRENGTH (how much is it moving);
regime.py's compute_regime() is trend DIRECTION (which way) — different
axes, both live in this package since they're both "regime classification."

Split out of the old single regime_manager.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

ADX_GATED_STRATEGIES is monkey-patched by scripts/ab_tests/
ab_test_mid_brk_adx_gate.py, but on `strategy_router.ADX_GATED_STRATEGIES`
(a separate, independently value-imported copy inside the strategy_router
package's own namespace) — NOT on `regime_manager.ADX_GATED_STRATEGIES`
directly (confirmed via grep). So this module's own copy never needs a
live dotted lookup; a normal re-export is safe.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("celo_trader.regime_manager")

ADX_PERIOD           = 14
ADX_MIN              = 25.0
ADX_GATED_STRATEGIES = {"INST_ORB", "MID_BRK", "TREND_CONT", "CHAN_BREAK", "VWAP_PB", "GAP_GO"}
# GAP_GO added 2026-07-23 — it's a momentum/breakout continuation play, the
# same family as INST_ORB/TREND_CONT/CHAN_BREAK, all of which are gated here.
# A gap without real directional participation (chop regime) is the
# textbook false-start gap-and-go fails on.
# VWAP_PB added 2026-07-15: it's trend-CONTINUATION, not mean-reversion —
# in low-ADX chop, VWAP acts as an attractor, not support (10% WR in audit).


def compute_adx_series(df: pd.DataFrame, period: int = ADX_PERIOD) -> "pd.Series | None":
    """
    Wilder ADX(14) computed on 5-min resampled bars.
    Accepts mixed-timeframe input (live passes 5-min history + today's 1-min).
    Returns a Series indexed by 5-min bucket timestamps, or None if not enough data.
    """
    try:
        d = df[["time", "high", "low", "close"]].dropna().copy()
        d = (d.set_index("time")
              .resample("5min")
              .agg({"high": "max", "low": "min", "close": "last"})
              .dropna())
        if len(d) < period * 2:
            return None   # not enough bars for a meaningful ADX

        up, dn   = d["high"].diff(), -d["low"].diff()
        plus_dm  = up.where((up > dn) & (up > 0), 0.0)   # +DM
        minus_dm = dn.where((dn > up) & (dn > 0), 0.0)   # -DM
        tr = pd.concat([d["high"] - d["low"],
                        (d["high"] - d["close"].shift()).abs(),
                        (d["low"]  - d["close"].shift()).abs()], axis=1).max(axis=1)

        alpha = 1.0 / period   # Wilder smoothing = EMA with alpha 1/N
        atr   = tr.ewm(alpha=alpha, adjust=False).mean()
        pdi   = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
        mdi   = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
        dx    = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0.0, float("nan"))
        return dx.ewm(alpha=alpha, adjust=False).mean()
    except Exception as exc:
        logger.debug("compute_adx_series failed: %s", exc)
        return None


def compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> "float | None":
    """Latest ADX value, or None if unavailable (fail-open: no gate applied)."""
    s = compute_adx_series(df, period)
    if s is None or s.empty:
        return None
    v = s.iloc[-1]
    return float(v) if pd.notna(v) else None
