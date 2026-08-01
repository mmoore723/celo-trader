"""
backtest_exit_sim/state.py — ExitSimState: per-open-trade state carried
bar-to-bar.

Split out of the old single backtest_exit_sim.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

from typing import Optional

from trading.position_manager import _DELTA_APPROX

from backtest_exit_sim.constants import _INITIAL_ATR_MULT


class ExitSimState:
    """
    Per-open-trade state carried bar-to-bar, mirroring position_manager.py's
    per-position `ps` dict (peak underlying, ratcheting trail, VWAP breach
    counter, structural stop set once at entry).
    """

    __slots__ = (
        "direction", "entry_price", "entry_bar_time",
        "struct_stop_price", "initial_atr_stop", "atr_trail_stop",
        "peak_underlying", "vwap_breached_bars",
    )

    def __init__(
        self,
        direction: str,
        entry_price: float,
        entry_bar_time,
        struct_stop_price: Optional[float],
        atr_at_entry: Optional[float],
    ):
        self.direction         = direction
        self.entry_price       = entry_price
        self.entry_bar_time    = entry_bar_time
        self.struct_stop_price = struct_stop_price
        self.atr_trail_stop    = None
        self.peak_underlying   = None
        self.vwap_breached_bars = 0

        # Initial ATR-based stop (replaces the old flat 20% fallback), set
        # once at entry exactly like position_manager.py's first-tick logic.
        self.initial_atr_stop = None
        if atr_at_entry:
            _atr_opt_stop = entry_price - _INITIAL_ATR_MULT * atr_at_entry * _DELTA_APPROX
            self.initial_atr_stop = max(
                entry_price * 0.70, min(entry_price * 0.85, _atr_opt_stop)
            )
