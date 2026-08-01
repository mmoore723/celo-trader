"""
strategies/fvg/constants.py — strategy ID and tunables.

Split out of the old single strategies/fvg.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

STRATEGY_ID = "FVG"

# How many bars back to look for a liquidity sweep
_SWEEP_LOOKBACK = 15
