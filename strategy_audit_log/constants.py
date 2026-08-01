"""
strategy_audit_log/constants.py — display-name map for strategy IDs.

Split out of the old single strategy_audit_log.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

_STRAT_NAMES = {
    "INST_ORB":   "Opening Range Breakout",
    "BOS_MSS":    "Break of Structure",
    "VWAP_PB":    "VWAP Pullback",
    "FVG":        "Fair Value Gap",
    "IFVG":       "Inverted Fair Value Gap",
    "MID_BRK":    "Mid-Day Breakdown",
    "AFT_REV":    "Afternoon Reversal",
    "TREND_CONT": "Trend Continuation",
    "CHAN_BREAK":  "Channel Rejection",
}
