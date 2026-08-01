"""
risk/target.py — Structure-based (not fixed +50%) profit target.

TargetMixin — mixed into RiskManager (risk/manager.py). Split out of risk.py
(2026-08-01, file-size cleanup); no logic changed, only relocated. Pairs with
risk/structural.py's stop-side logic.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("celo_trader.risk")

DELTA_APPROX = 0.40   # ATM option delta approximation, same as risk/structural.py


class TargetMixin:
    def structural_target_price(
        self,
        entry_price: float,
        underlying_current: float,
        direction: str,
        or_high: Optional[float] = None,
        or_low: Optional[float] = None,
        prev_day_high: Optional[float] = None,
        prev_day_low: Optional[float] = None,
        vwap_upper2: Optional[float] = None,
        vwap_lower2: Optional[float] = None,
    ) -> float:
        """
        Dynamic profit target derived from chart structure, not a fixed +50%.

        Priority for CALL (bullish): previous day high, OR double-extension,
        VWAP +2sigma, then static +50% fallback.
        Priority for PUT (bearish): previous day low, OR double-extension
        (downward), VWAP -2sigma, then static +50% fallback.

        The chosen target must clear effective_min_rr() vs the structural
        stop; falls through candidates in order, else static +50%.
        """
        def underlying_to_option_target(underlying_target: float) -> float:
            move = abs(underlying_target - underlying_current)
            return round(entry_price + move * DELTA_APPROX, 4)

        candidates: list[float] = []

        if direction == "bullish":
            if prev_day_high and prev_day_high > underlying_current:
                candidates.append(prev_day_high)
            if or_high and or_low:
                or_range  = or_high - or_low
                or_double = or_high + or_range
                if or_double > underlying_current:
                    candidates.append(or_double)
            if vwap_upper2 and vwap_upper2 > underlying_current:
                candidates.append(vwap_upper2)
        else:  # bearish / PUT
            if prev_day_low and prev_day_low < underlying_current:
                candidates.append(prev_day_low)
            if or_high and or_low:
                or_range  = or_high - or_low
                or_double = or_low - or_range
                if or_double < underlying_current:
                    candidates.append(or_double)
            if vwap_lower2 and vwap_lower2 < underlying_current:
                candidates.append(vwap_lower2)

        # Nearest first — most achievable
        candidates.sort(key=lambda c: abs(c - underlying_current))

        _min_rr   = self.effective_min_rr()
        static_sl = self.stop_loss_price(entry_price)
        net_risk  = entry_price - static_sl

        for underlying_tgt in candidates:
            opt_tgt = underlying_to_option_target(underlying_tgt)
            net_rew = opt_tgt - entry_price
            rr      = net_rew / net_risk if net_risk > 0 else 0
            if rr >= _min_rr and opt_tgt > entry_price:
                logger.debug(
                    "structural_target: using %.4f (underlying %.4f) R:R=%.2f",
                    opt_tgt, underlying_tgt, rr,
                )
                return opt_tgt

        return self.stage1_exit_price(entry_price)
