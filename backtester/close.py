"""
backtester/close.py — CloseMixin: _close_bt_trade, records a simulated
trade (with the entry-signal snapshot used for post-hoc win/loss analysis)
and returns its P&L.

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.
"""

from typing import Optional


class CloseMixin:

    # ── Trade recorder ────────────────────────────────────────────────────────

    def _close_bt_trade(
        self,
        entry_price: float,
        exit_price: float,
        n_contracts: int,
        option_type: str,
        reason: str,
        entry_hour: int = 10,
        held_minutes: float = 0.0,
        strategy_id: str = "UNKNOWN",
        date: str = "",
        confidence: float = 0.0,
        rvol: float = 0.0,
        meta: Optional[dict] = None,
    ) -> float:
        """
        Record a simulated trade and return its P&L.

        P&L uses real contract math: (exit - entry) × contracts × 100
        This is what the live bot computes in database.close_trade().

        confidence/rvol/meta (added 2026-07-17) capture what the ENTRY signal
        looked like — needed to find what actually distinguishes winning
        trades from losing ones within a strategy, instead of guessing at a
        single confidence-threshold knob. See diag_trend_cont_features.py.
        """
        if entry_price <= 0.0 or n_contracts <= 0:
            return 0.0
        pnl = (exit_price - entry_price) * n_contracts * 100
        self.trades.append({
            "strategy_id":   strategy_id,
            "option_type":   option_type,
            "direction":     "long" if option_type == "call" else "short",
            "entry_price":   entry_price,
            "exit_price":    exit_price,
            "contracts":     n_contracts,
            "pnl":           round(pnl, 2),
            "exit_reason":   reason,
            "entry_hour":    entry_hour,
            "held_minutes":  held_minutes,
            "date":          date,
            "entry_confidence": confidence,
            "entry_rvol":        rvol,
            "entry_meta":        meta or {},
        })
        return pnl

