"""
signals/__init__.py — Pure ORB Signal Engine.

ALL secondary indicator logic (RSI, MACD, Bollinger Bands, ADX, candlestick
patterns, multi-timeframe aggregation) has been removed.  The live trading
pipeline is 100% Price + Volume + VWAP.

ORB Signal Logic:
  1. Opening range  = first 5-minute candle of the session (09:30–09:35 ET)
  2. Breakout gate  = subsequent candle closes OUTSIDE the OR High/Low
  3. Volume gate    = breakout candle RVOL ≥ 200% of the 10-day same-slot avg
  4. VWAP gate      = price above VWAP for calls, below VWAP for puts

Returns:
  detect_orb_breakout() → Optional[tuple[str, float]]
    ("bullish" | "bearish",  rvol_of_breakout_candle)  |  None

The RVOL value is passed to risk.evaluate_rr() and logged as
Entry_Volume_Multiplier on every trade_opened event.

Split out of the old single signals.py (2026-08-01, file-size cleanup); no
logic changed, only relocated across data_helpers.py, volume.py,
earnings.py, vwap.py, rvol.py, atr.py, ranges.py, and orb_breakout.py.
Re-exports every public name so every existing `from signals import X`
call site across the app keeps working unchanged.
"""

from signals.data_helpers import bars_to_df
from signals.volume import is_volume_sufficient, relative_volume_rank
from signals.earnings import is_near_earnings
from signals.vwap import compute_vwap, compute_vwap_bands
from signals.rvol import compute_rvol
from signals.atr import compute_atr
from signals.ranges import get_opening_range
from signals.orb_breakout import ORB_SIGNAL_MIN, ORB_RVOL_THRESHOLD, detect_orb_breakout

__all__ = [
    "bars_to_df",
    "is_volume_sufficient", "relative_volume_rank",
    "is_near_earnings",
    "compute_vwap", "compute_vwap_bands",
    "compute_rvol",
    "compute_atr",
    "get_opening_range",
    "ORB_SIGNAL_MIN", "ORB_RVOL_THRESHOLD", "detect_orb_breakout",
]
