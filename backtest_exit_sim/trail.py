"""
backtest_exit_sim/trail.py — _update_trail_and_vwap(): ratchets the
ATR/swing trail and updates the VWAP-breach counter for one bar.

Split out of the old single backtest_exit_sim.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from trading.position_manager import (
    _structural_swing_stop,
    _underlying_stop_to_option,
    _MIN_TRAIL_WARMUP_MIN,
    _SWING_LOOKBACK,
    _VWAP_5M_BREACH_BARS,
)
from trading.mtf_features import compute_adx, ema_stack_aligned
from backtest_trail_multiplier import dynamic_trail_multiplier
from backtest_stage1_signals import compute_stage1_signals

from backtest_exit_sim.constants import _TRAIL_PROFIT_GATE
from backtest_exit_sim.risk_instance import _risk
from backtest_exit_sim.state import ExitSimState


def _update_trail_and_vwap(
    state: ExitSimState, day_df: pd.DataFrame, idx: int, current_opt_price: float,
    df_1h: Optional[pd.DataFrame] = None, df_15m: Optional[pd.DataFrame] = None,
) -> tuple[Optional[float], bool, Optional[float], bool]:
    """
    Ratchets the ATR/swing trail and updates the VWAP-breach counter for one
    bar. Returns (vwap_value, trend_dead, atr_target_price, momentum_fading)
    for this bar. Mutates `state`.

    atr_target_price/momentum_fading (added 2026-07-21) feed the dynamic
    stage1 trigger in risk.py — same signals/formula as live's
    position_manager.py, recomputed fresh each bar (not frozen at entry) so
    the target adapts as volatility/momentum change through the trade.
    """
    bar = day_df.iloc[idx]
    underlying_now = float(bar["close"])

    if state.direction == "bullish":
        state.peak_underlying = max(state.peak_underlying or underlying_now, underlying_now)
    else:
        state.peak_underlying = min(state.peak_underlying or underlying_now, underlying_now)

    atr = float(bar["atr"]) if "atr" in day_df.columns and pd.notna(bar.get("atr")) else None
    elapsed_min = (bar["time"] - state.entry_bar_time).total_seconds() / 60

    # BUG FIX 2026-07-21: this was hardcoded to 0.0 and never actually used,
    # so the trail armed after 5 minutes elapsed REGARDLESS of profit — live
    # requires +15% option gain too (position_manager.py's `_trail_profit_
    # gate`). Without this, the trail was firing almost immediately on nearly
    # every trade (5-min bars mean elapsed_min>=5 after just ONE bar), which
    # is exactly why atr_trail_stop dominated the exit-reason mix in both
    # audit runs today. Confirmed via the exit-mix data, not assumed.
    opt_gain_pct = (
        (current_opt_price - state.entry_price) / state.entry_price
        if state.entry_price else 0.0
    )

    if (atr is not None
            and elapsed_min >= _MIN_TRAIL_WARMUP_MIN
            and opt_gain_pct >= _TRAIL_PROFIT_GATE
            and state.peak_underlying is not None):
        # Point-in-time slices — only bars closed at or before the current
        # bar are visible, same no-lookahead rule as the rest of this file.
        _bar_time  = bar["time"]
        _1h_slice  = (df_1h[df_1h["time"] <= _bar_time]  if df_1h  is not None and not df_1h.empty  else None)
        _15m_slice = (df_15m[df_15m["time"] <= _bar_time] if df_15m is not None and not df_15m.empty else None)
        trail_mult = dynamic_trail_multiplier(
            state.direction, _1h_slice, day_df.iloc[: idx + 1], _15m_slice,
        )
        if state.direction == "bullish":
            atr_stop_u = state.peak_underlying - trail_mult * atr
        else:
            atr_stop_u = state.peak_underlying + trail_mult * atr
        atr_stop_opt = _underlying_stop_to_option(state.entry_price, underlying_now, atr_stop_u)

        swing_u = _structural_swing_stop(day_df.iloc[: idx + 1], state.direction, lookback=_SWING_LOOKBACK)
        if swing_u is not None:
            swing_opt = _underlying_stop_to_option(state.entry_price, underlying_now, swing_u)
            new_trail = max(atr_stop_opt, swing_opt)
        else:
            new_trail = atr_stop_opt

        # Ratchet: trail can only tighten, never loosen (matches live).
        if state.atr_trail_stop is None or new_trail > state.atr_trail_stop:
            state.atr_trail_stop = new_trail

    vwap = float(bar["vwap"]) if "vwap" in day_df.columns and pd.notna(bar.get("vwap")) else None
    if vwap is not None:
        breached_now = (
            (state.direction == "bullish" and underlying_now < vwap) or
            (state.direction == "bearish" and underlying_now > vwap)
        )
        state.vwap_breached_bars = state.vwap_breached_bars + 1 if breached_now else 0

    trend_dead = False
    if state.vwap_breached_bars >= _VWAP_5M_BREACH_BARS:
        bar_slice = day_df.iloc[: idx + 1]
        adx = compute_adx(bar_slice)
        ema_ok = ema_stack_aligned(bar_slice, state.direction)
        trend_dead = (adx is not None and adx < 20) and not ema_ok

    # Dynamic stage1 trigger inputs (2026-07-21) — split out to
    # backtest_stage1_signals.py to keep this file under 200 lines.
    atr_target_price, momentum_fading = compute_stage1_signals(
        state.direction, state.entry_price, atr,
        _risk.STAGE1_ATR_TARGET_MULT, day_df.iloc[: idx + 1],
        require_both=_risk.STAGE1_MOMENTUM_REQUIRE_BOTH,
        target_min_pct=_risk.STAGE1_TARGET_MIN_PCT,
    )

    return vwap, trend_dead, atr_target_price, momentum_fading
