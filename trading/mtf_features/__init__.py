"""
trading/mtf_features/ — multi-timeframe technical feature helpers.

Split out of the old single trading/mtf_features.py (2026-08-01, file-size
cleanup); no logic changed, only relocated across:
  - adx.py:          compute_adx() — Wilder's ADX on 1-min bars
  - ema_stack.py:     ema_stack_aligned() — EMA8/21/50 stack-direction check
  - rsi_macd.py:      compute_rsi(), compute_macd_hist()
  - mtf_alignment.py: trend_bias_1h(), compute_mtf_alignment()

No monkeypatching of this module's names was found anywhere in the codebase
(grep-verified), so this __init__.py just re-exports normally — no live
dotted-lookup trick needed.
"""

from trading.mtf_features.adx import compute_adx
from trading.mtf_features.ema_stack import ema_stack_aligned
from trading.mtf_features.rsi_macd import compute_rsi, compute_macd_hist
from trading.mtf_features.mtf_alignment import trend_bias_1h, compute_mtf_alignment

__all__ = [
    "compute_adx",
    "ema_stack_aligned",
    "compute_rsi",
    "compute_macd_hist",
    "trend_bias_1h",
    "compute_mtf_alignment",
]
