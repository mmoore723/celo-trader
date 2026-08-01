"""
strategies/ifvg/constants.py — strategy ID and tunables.

Split out of the old single strategies/ifvg.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

STRATEGY_ID = "IFVG"

_GAP_LOOKBACK    = 25   # max bars back to look for original gap
_RETEST_MAX_BARS = 15   # retest must happen within this many bars of violation
