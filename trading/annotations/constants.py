"""
trading/annotations/constants.py — cap + default color map for chart annotations.

Split out of the old single trading/annotations.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

_MAX_ANNOTATIONS = 100   # per-ticker — oldest dropped when exceeded

# Default hex colors keyed by "STRATEGY_direction" or just "STRATEGY"
_COLORS: dict[str, str] = {
    "V2_ORB_PULLBACK": "#eab308",
    "V2_SPY_TREND_CONT": "#8b5cf6",
    "V2_SPY_AFTERNOON_FVG": "#06b6d4",
    "V2_TSLA_TWO_LEG_TREND_PULLBACK": "#3b82f6",
    "signal_bullish": "#22c55e",   # green  — entry marker
    "signal_bearish": "#ef4444",   # red    — entry marker (put)
    "veto":           "#64748b",   # slate  — vetoed
    "stage1":         "#f59e0b",   # amber  — Stage 1 hit
    "default":        "#94a3b8",
}
