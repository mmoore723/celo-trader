"""
trading/annotations/constants.py — cap + default color map for chart annotations.

Split out of the old single trading/annotations.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

_MAX_ANNOTATIONS = 100   # per-ticker — oldest dropped when exceeded

# Default hex colors keyed by "STRATEGY_direction" or just "STRATEGY"
_COLORS: dict[str, str] = {
    "FVG_bullish":    "#06b6d4",   # cyan
    "FVG_bearish":    "#f97316",   # orange
    "IFVG_bullish":   "#a855f7",   # purple
    "IFVG_bearish":   "#ec4899",   # pink
    "BOS_MSS":        "#84cc16",   # lime
    "BOS_MSS_bullish":"#84cc16",
    "BOS_MSS_bearish":"#f87171",   # red-300 (bearish BOS)
    "VWAP_PB":        "#3b82f6",   # blue
    "MID_BRK":        "#ef4444",   # red
    "INST_ORB":       "#eab308",   # gold
    "AFT_REV":        "#14b8a6",   # teal
    "TREND_CONT":     "#8b5cf6",   # violet
    "signal_bullish": "#22c55e",   # green  — entry marker
    "signal_bearish": "#ef4444",   # red    — entry marker (put)
    "veto":           "#64748b",   # slate  — vetoed
    "stage1":         "#f59e0b",   # amber  — Stage 1 hit
    "default":        "#94a3b8",
}
