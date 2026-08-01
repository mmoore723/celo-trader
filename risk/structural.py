"""
risk/structural.py — Structure-based (not fixed-%) stop-loss pricing.

find_structural_stop() is a pure helper (no RiskManager state). StructuralMixin
is mixed into RiskManager (risk/manager.py). Split out of risk.py (2026-08-01,
file-size cleanup); no logic changed, only relocated. See risk/target.py for
the matching structural profit-target logic.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("celo_trader.risk")

DELTA_APPROX = 0.40   # ATM option delta approximation (conservative, near-expiry)


def find_structural_stop(
    df,                     # pd.DataFrame with OHLCV + "time" column
    direction: str,         # "bullish" (CALL) or "bearish" (PUT)
    lookback: int = 30,     # recent bars to scan for pivots
    pivot_bars: int = 3,    # bars on each side for pivot confirmation
) -> Optional[float]:
    """
    Return the most recent structural swing price that defines the stop-loss.

    CALL (bullish): stop = most recent Swing Low — last structural support.
    PUT (bearish):  stop = most recent Swing High — last structural resistance.

    Uses an N-bar pivot: a bar whose high (or low) exceeds all bars within
    `pivot_bars` bars on each side. Returns None when insufficient data
    exists; callers should fall back to ORB_STOP_PCT in that case.
    """
    try:
        if df is None or len(df) < 2 * pivot_bars + 1:
            return None

        window = df.iloc[-min(lookback, len(df)):].reset_index(drop=True)
        n      = len(window)

        pivots = []
        for i in range(pivot_bars, n - pivot_bars):
            bar   = window.iloc[i]
            left  = window.iloc[i - pivot_bars : i]
            right = window.iloc[i + 1 : i + pivot_bars + 1]

            if direction == "bullish":
                if (float(bar["low"]) < float(left["low"].min()) and
                        float(bar["low"]) < float(right["low"].min())):
                    pivots.append(float(bar["low"]))
            else:
                if (float(bar["high"]) > float(left["high"].max()) and
                        float(bar["high"]) > float(right["high"].max())):
                    pivots.append(float(bar["high"]))

        return pivots[-1] if pivots else None

    except Exception as ex:
        logger.debug("find_structural_stop error (%s): %s", direction, ex)
        return None


class StructuralMixin:
    def structural_stop_price(
        self,
        entry_price: float,
        df,                       # pd.DataFrame of underlying OHLCV bars
        direction: str,           # "bullish" or "bearish"
        option_multiplier: float = 100.0,
    ) -> float:
        """
        Dynamic structural stop-loss based on market structure, not a fixed %.

        CALL: stop at the option premium implied by the most recent underlying
        Swing Low. PUT: implied by the most recent Swing High. Converts via
        the ATM delta approximation. Falls back to the static ORB_STOP_PCT
        when no swing pivot is found — never removes the hard stop.
        """
        swing_price = find_structural_stop(df, direction)

        if swing_price is None:
            logger.debug(
                "structural_stop_price: no swing found for %s — using ORB_STOP_PCT",
                direction,
            )
            return self.stop_loss_price(entry_price)

        try:
            underlying_current = float(df["close"].iloc[-1])
        except Exception:
            return self.stop_loss_price(entry_price)

        underlying_move = abs(underlying_current - swing_price)
        option_move      = underlying_move * DELTA_APPROX
        struct_stop      = entry_price - option_move
        static_stop      = self.stop_loss_price(entry_price)

        # Validity guard: if the swing is within noise distance of price, the
        # implied stop would be >= entry and trigger immediately.
        if struct_stop >= entry_price:
            result = static_stop
        else:
            result = max(static_stop, struct_stop)

        logger.debug(
            "structural_stop: direction=%s swing=%.4f underlying_move=%.4f "
            "option_move=%.4f entry=%.4f struct_stop=%.4f final=%.4f",
            direction, swing_price, underlying_move, option_move,
            entry_price, struct_stop, result,
        )
        return round(result, 4)

    def structural_stop_from_level(
        self,
        entry_price: float,
        underlying_current: float,
        stop_underlying: float,
    ) -> float:
        """
        Convert an explicit underlying stop level (entry_bar_high/low from
        the entry signal) into an option stop price. Floored at the static
        30% stop so this is never more permissive than the hard risk limit.
        """
        underlying_move = abs(stop_underlying - underlying_current)
        option_move     = underlying_move * DELTA_APPROX
        struct_stop     = entry_price - option_move
        static_stop     = self.stop_loss_price(entry_price)
        if struct_stop >= entry_price:
            result = static_stop
        else:
            result = max(static_stop, struct_stop)
        logger.debug(
            "structural_stop_from_level: underlying_now=%.4f stop_level=%.4f "
            "underlying_move=%.4f option_move=%.4f entry=%.4f result=%.4f",
            underlying_current, stop_underlying, underlying_move, option_move,
            entry_price, result,
        )
        return round(result, 4)
