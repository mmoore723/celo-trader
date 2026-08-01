"""
backtest_exit_sim/risk_instance.py — the single shared RiskManager instance
used by the backtest exit engine, synced to config's live-tunable defaults.

Split out of the old single backtest_exit_sim.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

This is the ONE place `_risk = RiskManager()` is constructed for this
module. Three archived A/B test scripts (scripts/ab_tests/
ab_test_stage1_dynamic.py, ab_test_momentum_fade_tuning.py,
ab_test_stage1_target.py) do `import backtest_exit_sim` then mutate
attributes on this exact instance directly, e.g.
`backtest_exit_sim._risk.ORB_STAGE1_GAIN = value`. Unlike the scalar/list
globals handled elsewhere in this refactor (strategies/vwap_pb.py,
strategy_router.py, logger_config's _SECRET_PATTERNS), attribute mutation
on a shared OBJECT doesn't have a staleness problem — as long as every
consumer (trail.py, evaluate.py, and this package's __init__.py) imports
this SAME `_risk` object by reference rather than constructing their own,
`obj.attr = value` mutates the one shared instance's __dict__ and every
holder of that reference sees it immediately, since attribute lookups are
always live. No lazy self-import trick needed here.
"""

from risk import RiskManager
from config import _DEFAULTS

_risk = RiskManager()
# BUG FIX 2026-07-21: risk.py's class default (ORB_STAGE1_GAIN=0.25) is
# stale/overridden in live trading — trading/entry.py always sets the
# per-request instance value from the user's settings
# (orb_stage1_gain_pct, default 50 in config.py's _DEFAULTS), so live
# actually runs at +50%, not +25%. This backtest module never applied
# that override, so every run today was silently testing a 25% profit-
# lock, not the 50% live actually uses. Backtests have no per-user
# settings context, so the canonical default from config.py is the
# correct fidelity choice here.
_risk.ORB_STAGE1_GAIN = float(_DEFAULTS.get("orb_stage1_gain_pct", 50)) / 100.0
# BUG FIX 2026-07-22 (full-audit finding 1.2): the line above only synced
# ORB_STAGE1_GAIN. evaluate_exit_conditions() (risk.py) also reads
# ORB_STOP_PCT and 5 more stage1-tuning knobs directly, and live syncs ALL
# 7 every tick (see trading/entry.py's "Sync user-editable trade parameters"
# block). This module is specifically the one that claims fidelity with
# live's real exit engine, so it's the highest-priority place to get this
# right — left unsynced, these 6 were silently at risk.py's raw class
# defaults, correct today only by coincidence.
_risk.ORB_STOP_PCT                 = float(_DEFAULTS.get("orb_stop_loss_pct", 20)) / 100.0
_risk.STAGE1_DYNAMIC_ENABLED        = bool(_DEFAULTS.get("stage1_dynamic_enabled", True))
_risk.STAGE1_ATR_TARGET_MULT        = float(_DEFAULTS.get("stage1_atr_target_mult", 2.0))
_risk.STAGE1_FLOOR_FRACTION_OF_TARGET = float(_DEFAULTS.get("stage1_floor_fraction_of_target", 75)) / 100.0
_risk.STAGE1_RVOL_FADE_THRESHOLD    = float(_DEFAULTS.get("stage1_rvol_fade_threshold", 1.0))
_risk.STAGE1_MOMENTUM_REQUIRE_BOTH  = bool(_DEFAULTS.get("stage1_momentum_require_both", True))
