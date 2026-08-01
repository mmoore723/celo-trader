"""
backtest_exit_sim/constants.py — pinned constants mirroring un-named
literals in position_manager.py.

Split out of the old single backtest_exit_sim.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

# Live gates the ATR trail on +15% option gain (position_manager.py line ~509,
# `_trail_profit_gate = _opt_gain_pct >= 0.15`) — not a named constant there,
# so pinned here with the same value + a pointer back to the source line.
_TRAIL_PROFIT_GATE = 0.15

# Initial ATR stop multiplier, before the trail arms (position_manager.py
# `_init_mult = 2.5`, same non-named-constant situation as above).
_INITIAL_ATR_MULT = 2.5
