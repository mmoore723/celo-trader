"""
strategies/chan_break/constants.py — Strategy ID and tunable thresholds.

Split out of the old single strategies/chan_break.py (2026-08-01,
file-size cleanup); no logic changed, only relocated.
"""

STRATEGY_ID = "CHAN_BREAK"

_MIN_SLOPE   = 0.008   # per-bar slope below this = flat channel = noise (raised from 0.002)
_MAX_AGE     = 40      # bars; older pivots = stale channel
_TOUCH_TOL   = 0.0015  # 0.15% touch tolerance (loosened from 0.3% — too many near-misses)
