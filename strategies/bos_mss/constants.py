"""
strategies/bos_mss/constants.py — strategy ID and tunables.

Split out of the old single strategies/bos_mss.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

STRATEGY_ID = "BOS_MSS"

# Minimum session bars before BOS_MSS is eligible to fire
_MIN_BARS = 10

# RVOL floor for BOS_MSS (structure-confirmed, so relaxed slightly)
_RVOL_FLOOR = 1.5
