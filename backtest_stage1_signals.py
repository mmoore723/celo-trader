"""
backtest_stage1_signals.py — Dynamic stage1 trigger inputs for the backtest
exit engine.

Split out of backtest_exit_sim.py (2026-07-21, same reason as
backtest_trail_multiplier.py: keeps both files under the project's
200-line-per-file convention).

Computes the two inputs risk.py's dynamic stage1 trigger needs — an
ATR-scaled profit target and a momentum-fade flag (RSI exhaustion / 5m
MACD rollover) — using the exact same formula and thresholds as live's
position_manager.py, recomputed fresh each bar (not frozen at entry) so
the backtest matches how live actually behaves tick-to-tick.

Background: ab_test_stage1_target.py found the OLD flat-%-only stage1
trigger negative at 50/30/20%, with ~0 winning trades ever reaching the
static target. Research (10+ sources, CLAUDE.md rule 9) supports ATR-scaled
partial profit-taking + momentum/volume confirmation over a single fixed
number — see risk.py's STAGE1_DYNAMIC_ENABLED comment block for the full
research trail.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from trading.position_manager import (
    _DELTA_APPROX,
    _RSI_EXHAUST_CALL,
    _RSI_EXHAUST_PUT,
    _MACD_FADE_BARS,
)
from trading.mtf_features import compute_rsi, compute_macd_hist


def compute_stage1_signals(
    direction: str,
    entry_price: float,
    atr: Optional[float],
    atr_target_mult: float,
    bar_slice: pd.DataFrame,
    require_both: bool = False,
) -> tuple[Optional[float], bool]:
    """
    Returns (atr_target_price, momentum_fading) for the current bar.

    atr_target_price: entry_price + atr_target_mult × ATR × delta-approx,
    or None if no ATR data yet (risk.py fails open to the flat % in that
    case, same fallback pattern as the ATR trail elsewhere).

    momentum_fading: RSI exhaustion (5m RSI >=72 call / <=28 put) combined
    with 5m MACD histogram declining for _MACD_FADE_BARS consecutive bars
    — same signals/thresholds already used for the trail multiplier, reused
    here for the stage1 trigger too (no separate copy to drift out of sync).

    require_both (2026-07-21, from RiskManager.STAGE1_MOMENTUM_REQUIRE_BOTH):
    diagnosis after ab_test_stage1_dynamic.py found ALL stage1 exits firing
    via momentum_fade with the OR combination — either signal alone was
    enough to trigger at just the +10% floor, never giving the ATR target a
    chance. False=OR (current live default), True=AND (untested candidate
    — requires both signals to agree before firing).
    """
    atr_target_price = None
    if atr is not None:
        atr_target_price = entry_price + atr_target_mult * atr * _DELTA_APPROX

    momentum_fading = False
    if len(bar_slice) >= 5:
        rsi = compute_rsi(bar_slice)
        rsi_exhausted = (
            (rsi is not None and direction == "bullish" and rsi >= _RSI_EXHAUST_CALL) or
            (rsi is not None and direction == "bearish" and rsi <= _RSI_EXHAUST_PUT)
        )
        macd_hist = compute_macd_hist(bar_slice)
        macd_fading = len(macd_hist) >= _MACD_FADE_BARS and all(
            macd_hist[-(i + 1)] < macd_hist[-(i + 2)]
            for i in range(_MACD_FADE_BARS - 1)
        )
        momentum_fading = (rsi_exhausted and macd_fading) if require_both else (rsi_exhausted or macd_fading)

    return atr_target_price, momentum_fading
