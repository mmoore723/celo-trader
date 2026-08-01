"""
strategies/inst_orb/constants.py — Strategy ID, session-window timing, and
retest-tolerance thresholds for INST_ORB.

Split out of the old single strategies/inst_orb.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

STRATEGY_ID = "INST_ORB"

# Session window — breakout must be detected by 10:30; retest can complete by 10:45
_SESSION_START      = 9  * 60 + 45   # 09:45 — breakout detection window start
_BREAKOUT_DEADLINE  = 10 * 60 + 30   # 10:30 — breakout must be seen before this
_SESSION_END        = 10 * 60 + 45   # 10:45 — retest entry deadline

# Retest tolerance: how close price must come to the OR boundary to count as a retest.
# 0.15% of the boundary price, minimum $0.05. On SPY (~$730) this is ~$1.10.
# Prevents a "close enough" touch on a fast move from triggering too early.
_RETEST_TOLERANCE_PCT = 0.0015   # 0.15% of boundary price
_RETEST_TOLERANCE_MIN = 0.05     # absolute floor
