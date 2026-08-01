"""
backtest_exit_sim/evaluate.py — evaluate_bt_exit(): one bar of the real
risk.py exit hierarchy.

Split out of the old single backtest_exit_sim.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from backtest_exit_sim.risk_instance import _risk
from backtest_exit_sim.state import ExitSimState
from backtest_exit_sim.trail import _update_trail_and_vwap


def evaluate_bt_exit(
    state: ExitSimState,
    day_df: pd.DataFrame,
    idx: int,
    current_opt_price: float,
    opt_bar_best: float,
    opt_bar_worst: float,
    stage1_done: bool,
    stage1_be_price: Optional[float],
    peak_opt_price: float,
    rvol: float,
    df_1h: Optional[pd.DataFrame] = None,
    df_15m: Optional[pd.DataFrame] = None,
) -> tuple[bool, str]:
    """
    One bar of the real risk.py exit hierarchy. Checks the conservative
    (worst-case) price first — this is what actually threatens a stop —
    then the best-case price for profit-taking conditions, same "stops
    before targets" convention the backtester already used pre-fix.

    While stage1_done, only the worst-case price is checked: stage2's
    floor and the winner time-cap are the only live conditions, and both
    are either adverse-price or elapsed-time based, not profit-target based.
    """
    bar = day_df.iloc[idx]
    vwap, trend_dead, atr_target_price, momentum_fading = _update_trail_and_vwap(
        state, day_df, idx, current_opt_price, df_1h=df_1h, df_15m=df_15m,
    )
    trail_armed = state.atr_trail_stop is not None
    effective_atr_stop = state.atr_trail_stop or state.initial_atr_stop

    def _check(current_price: float) -> tuple[bool, str]:
        return _risk.should_exit(
            state.entry_price, current_price,
            entry_time        = state.entry_bar_time,
            now                = bar["time"],
            stage1_done        = stage1_done,
            stage1_be_price    = stage1_be_price,
            peak_price         = peak_opt_price,
            struct_stop_price  = state.struct_stop_price,
            atr_trail_stop     = effective_atr_stop,
            trail_armed        = trail_armed,
            vwap               = vwap,
            vwap_breached      = state.vwap_breached_bars >= 1,
            trend_dead         = trend_dead,
            direction          = state.direction,
            rvol               = rvol,
            atr_target_price   = atr_target_price,   # dynamic stage1 trigger (2026-07-21)
            momentum_fading    = momentum_fading,
        )

    should_exit, reason = _check(opt_bar_worst)
    if should_exit or stage1_done:
        return should_exit, reason

    return _check(opt_bar_best)
