"""
playbook_examples/evaluators.py — The 8-strategy evaluator table, imported
directly from strategy_router.py (not via route_signals()) so offline
mining isn't gated by check_kill_lock() — see the package docstring.

Split out of the old single playbook_examples.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from strategy_router import (
    _eval_inst_orb,
    _eval_bos_mss,
    _eval_vwap_pullback,
    _eval_fvg,
    _eval_midday_breakdown,
    _eval_afternoon_reversal,
    _eval_trend_cont,
    _eval_chan_break,
    MarketStructureAnalyzer,
)

# How many bars of margin to pad around the display window when running swing
# (SH/SL) pivot detection — MarketStructureAnalyzer needs LOOKBACK (5) bars on
# BOTH sides of a candidate bar to confirm it as a pivot, so without this
# padding we'd silently miss pivots near the edges of the visible window.
_SWING_CONTEXT_PAD = MarketStructureAnalyzer.LOOKBACK + 1

_EVALUATORS = [
    ("INST_ORB",   _eval_inst_orb),
    ("BOS_MSS",    _eval_bos_mss),
    ("VWAP_PB",    _eval_vwap_pullback),
    ("FVG",        _eval_fvg),
    ("MID_BRK",    _eval_midday_breakdown),
    ("AFT_REV",    _eval_afternoon_reversal),
    ("TREND_CONT", _eval_trend_cont),
    ("CHAN_BREAK", _eval_chan_break),
]
