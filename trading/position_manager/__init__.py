"""
trading/position_manager/ — Adaptive position management with
structure-aware exits.

Split from the old single trading/position_manager.py into themed modules
(2026-08-01, file-size cleanup) — no logic changed anywhere, only relocated.
This __init__.py re-exports the exact same public names the old flat module
did, so every existing `from trading.position_manager import X` call site
elsewhere in the app (backtest_exit_sim.py, backtest_trail_multiplier.py,
backtest_stage1_signals.py, backtest_exit_sim_simplified.py,
trading/simplified_exit_live.py, trading/controls.py, trading/entry.py) is
unaffected:

  constants.py  — exit-engine tuning constants
  indicators.py — ATR/VWAP/swing math specific to the trailing stop
  helpers.py    — annotation snapshot + phantom-position reconciliation
  manage.py     — _manage_open_position: per-tick adaptive exit loop
  close.py      — _close_position: exit order execution + trade closeout

See trading/position_manager/manage.py's docstring for the full exit
hierarchy (also documented in risk/exits.py, the authoritative source).
"""

from trading.position_manager.constants import (
    _DELTA_APPROX,
    _MIN_TRAIL_WARMUP_MIN,
    _SWING_LOOKBACK,
    _VWAP_5M_BREACH_BARS,
    _TRAIL_MULT_BASE,
    _TRAIL_MULT_1H_WITH,
    _TRAIL_MULT_1H_AGAINST,
    _TRAIL_MULT_TIGHT,
    _RSI_EXHAUST_CALL,
    _RSI_EXHAUST_PUT,
    _MACD_FADE_BARS,
    _15M_SWING_PROX_PCT,
)
from trading.position_manager.indicators import (
    _compute_atr,
    _compute_vwap,
    _structural_swing_stop,
    _underlying_stop_to_option,
)
from trading.position_manager.helpers import _snapshot_exit_annotations, _reconcile_if_phantom
from trading.position_manager.manage import _manage_open_position
from trading.position_manager.close import _close_position

__all__ = [
    "_manage_open_position",
    "_close_position",
    "_structural_swing_stop",
    "_underlying_stop_to_option",
    "_compute_atr",
    "_compute_vwap",
    "_snapshot_exit_annotations",
    "_reconcile_if_phantom",
    "_DELTA_APPROX",
    "_MIN_TRAIL_WARMUP_MIN",
    "_SWING_LOOKBACK",
    "_VWAP_5M_BREACH_BARS",
    "_TRAIL_MULT_BASE",
    "_TRAIL_MULT_1H_WITH",
    "_TRAIL_MULT_1H_AGAINST",
    "_TRAIL_MULT_TIGHT",
    "_RSI_EXHAUST_CALL",
    "_RSI_EXHAUST_PUT",
    "_MACD_FADE_BARS",
    "_15M_SWING_PROX_PCT",
]
