"""
regime_manager/regime.py — macro-trend DIRECTION classifier (15-min EMA9/21).

Split out of the old single regime_manager.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

REGIME_GATE_ENABLED is read externally via live dotted access on the
PACKAGE object (`import regime_manager as _regime_mgr; _regime_mgr.
REGIME_GATE_ENABLED`) by router_gates/regime.py, and mutated the same way
by scripts/diagnostics/archive/ab_test_regime_manager.py. That pattern
already works correctly across a package split with no extra lazy-lookup
trick needed here, because both sides use module-reference (`import X as
alias`) semantics, not a value-copying `from X import NAME` — the alias
always points at the one shared module object, so attribute mutation is
visible immediately regardless of where REGIME_GATE_ENABLED's canonical
definition lives (confirmed via grep: nothing inside regime_manager itself
reads REGIME_GATE_ENABLED, only external consumers, and both already use
the dotted-access pattern).
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
