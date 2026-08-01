"""
strategies/fvg/sweep.py — _detect_liquidity_sweep(): ICT-style liquidity
sweep detector.

Split out of the old single strategies/fvg.py (2026-08-01, file-size
cleanup); no logic changed, only relocated. Imported directly by
strategies/ifvg.py (`from strategies.fvg import _detect_liquidity_sweep`)
— re-exported at the package level in strategies/fvg/__init__.py to keep
that call site unchanged.
"""

from __future__ import annotations

import logging

import pandas as pd

from strategies.base import MarketStructureAnalyzer

from strategies.fvg.constants import _SWEEP_LOOKBACK

logger = logging.getLogger("celo_trader.strategies.fvg")


def _detect_liquidity_sweep(today: pd.DataFrame, direction: str, msa: MarketStructureAnalyzer) -> bool:
    """
    Check whether a liquidity sweep occurred in the last _SWEEP_LOOKBACK bars.

    A sweep is a wick that:
      - Breaks BELOW a prior swing low (for a bullish FVG) — sell-side liquidity taken,
        smart money absorbed, gap forms in the reversal up.
      - Breaks ABOVE a prior swing high (for a bearish FVG) — buy-side liquidity taken,
        smart money distributed, gap forms in the reversal down.

    The sweep bar's CLOSE must be back on the correct side of the swing level —
    a full candle close through the level is a real breakout, not a sweep.

    Returns True if a qualifying sweep exists within the lookback window.
    """
    n = len(today)
    if n < _SWEEP_LOOKBACK + 3:
        return False

    window_start = max(0, n - _SWEEP_LOOKBACK)

    if direction == "bullish":
        # Need a bearish sweep: wick below prior swing low, close back above it
        sweep_level = msa.prev_swing_low() or msa.last_swing_low()
        if sweep_level is None:
            return False
        for i in range(window_start, n):
            bar = today.iloc[i]
            if float(bar["low"]) < sweep_level and float(bar["close"]) > sweep_level:
                logger.debug(
                    "Liquidity sweep detected (bullish): bar low=%.2f swept below %.2f, "
                    "closed at %.2f", float(bar["low"]), sweep_level, float(bar["close"])
                )
                return True

    else:  # bearish
        # Need a bullish sweep: wick above prior swing high, close back below it
        sweep_level = msa.prev_swing_high() or msa.last_swing_high()
        if sweep_level is None:
            return False
        for i in range(window_start, n):
            bar = today.iloc[i]
            if float(bar["high"]) > sweep_level and float(bar["close"]) < sweep_level:
                logger.debug(
                    "Liquidity sweep detected (bearish): bar high=%.2f swept above %.2f, "
                    "closed at %.2f", float(bar["high"]), sweep_level, float(bar["close"])
                )
                return True

    return False
