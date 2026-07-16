"""
regime_manager.py — Optional macro-trend regime classifier (2026-07-16).

Background
──────────
VWAP_PB and AFT_REV are currently disabled by default (proven negative
backtest expectancy — see trading/entry.py _STRAT_DEFAULTS for the numbers).
A proposal came in that they're actually failing because nothing enforces a
shared trend direction across strategies: VWAP_PB should only buy pullbacks
WITH the prevailing trend, and AFT_REV should be blocked from taking
reversal trades AGAINST a strong prevailing trend.

Two claims in that proposal did not hold up when checked against the code:
VWAP_PB already has an ADX >= 25 gate (strategy_router._ADX_GATED_STRATEGIES)
and still lost money with it; and the router already prevents two strategies
opening opposing trades on the same ticker in the same tick (single
top-confidence signal + conflict veto). So this module is not "the missing
piece" that guarantees a fix — it's a genuinely new, untested mechanism
(classify the macro trend on a HIGHER timeframe — 15-min EMA9/21 — than any
individual strategy currently checks) that deserves an honest A/B test
before anything is re-enabled live.

REGIME_GATE_ENABLED defaults to False. Flipping it does nothing to live
trading by itself — VWAP_PB and AFT_REV stay disabled in
trading/entry.py._STRAT_DEFAULTS regardless, until a backtest with this
gate ON actually shows positive expectancy. See ab_test_regime_manager.py.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("celo_trader.regime_manager")

REGIME_GATE_ENABLED = False   # master switch — OFF until proven in backtest

REGIME_TIMEFRAME = "15min"
REGIME_EMA_FAST  = 9
REGIME_EMA_SLOW  = 21

# Strategies whose signal direction must agree with the macro regime.
# VWAP_PB (trend-continuation pullback) and AFT_REV (afternoon reversal) are
# the two strategies the proposal specifically named. Everything else is
# left alone — this module only ever REMOVES signals, never adds them.
REGIME_GATED_STRATEGIES = {"VWAP_PB", "AFT_REV"}


def compute_regime_series(df: pd.DataFrame) -> "pd.Series | None":
    """
    Classify macro trend on a 15-min resample using EMA9 vs EMA21.
    Returns a Series of "bullish" | "bearish" | "neutral" indexed by 15-min
    bucket, or None if there isn't enough history. Fails open (None) rather
    than raising — callers must treat None/missing as "neutral" (no gate).
    """
    try:
        d = (df[["time", "close"]].dropna()
               .set_index("time")
               .resample(REGIME_TIMEFRAME)
               .last()
               .dropna())
        if len(d) < REGIME_EMA_SLOW:
            return None

        ema_fast = d["close"].ewm(span=REGIME_EMA_FAST, adjust=False).mean()
        ema_slow = d["close"].ewm(span=REGIME_EMA_SLOW, adjust=False).mean()

        regime = pd.Series("neutral", index=d.index, dtype="object")
        bullish = (ema_fast > ema_slow) & (d["close"] > ema_fast)
        bearish = (ema_fast < ema_slow) & (d["close"] < ema_fast)
        regime[bullish] = "bullish"
        regime[bearish] = "bearish"
        return regime
    except Exception as exc:
        logger.debug("compute_regime_series failed: %s", exc)
        return None


def compute_regime(df: pd.DataFrame) -> str:
    """Latest regime value, or 'neutral' (no restriction) if unavailable."""
    s = compute_regime_series(df)
    if s is None or s.empty:
        return "neutral"
    v = s.iloc[-1]
    return str(v) if pd.notna(v) else "neutral"


def regime_allows(strategy_id: str, direction: str, regime: str) -> bool:
    """
    True = signal permitted.

    Neutral regime never restricts anything — there's nothing conclusive to
    enforce, and the ADX gate already handles true chop for the strategies
    that have it. Only strategies in REGIME_GATED_STRATEGIES are constrained,
    and the rule is the same for both: signal direction must match the macro
    regime. For VWAP_PB this means "only buy dips / short bounces WITH the
    trend." For AFT_REV this means "no reversal calls AGAINST a strong trend."
    """
    if regime == "neutral":
        return True
    if strategy_id in REGIME_GATED_STRATEGIES:
        return direction == regime
    return True
