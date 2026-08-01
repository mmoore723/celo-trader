"""
risk/ — Risk management layer with Dynamic Sizing Ladder and Thread-Safe Locks.

Split from the old single risk.py into themed modules (2026-08-01, file-size
cleanup) — no logic changed anywhere, only relocated. This __init__.py
re-exports the exact same public names the old risk.py did, so every
existing `from risk import X` call site elsewhere in the app is unaffected:

  risk/kill_lock.py   — 24h trading freeze after the daily hard-loss cap
  risk/db_helpers.py  — persistent state reads/writes (peak price, today's P&L)
  risk/sizing.py      — SizingMixin: position sizing, risk %, slippage
  risk/rr.py          — RRMixin: pre-entry reward:risk gate
  risk/structural.py  — StructuralMixin + find_structural_stop: stop pricing
  risk/target.py      — TargetMixin: structure-based profit target
  risk/exits.py       — ExitsMixin: the adaptive exit engine (evaluate_exit_
                         conditions / should_exit)
  risk/guard.py       — GuardMixin + DailyLossLimitReached: can_trade gate,
                         daily-loss bookkeeping
  risk/manager.py      — RiskManager: assembles all mixins into one class

Growth Mode additions (unchanged from the original module docstring):
  - get_risk_tier(balance)          : returns 3% (<$50k) or 1% (>=$50k)
  - DAILY_LOSS_HARD_CAP_PCT = 0.10  : hard 10% daily cap, always enforced
  - kill lock                       : 24-hour trading freeze written to kill_lock.json
"""

from risk.kill_lock import set_kill_lock, check_kill_lock, clear_kill_lock
from risk.db_helpers import (
    db_mutex,
    get_todays_realized_pnl,
    persist_peak_price,
    recover_peak_price,
)
from risk.structural import find_structural_stop
from risk.guard import DailyLossLimitReached
from risk.manager import RiskManager

__all__ = [
    "RiskManager",
    "DailyLossLimitReached",
    "find_structural_stop",
    "set_kill_lock",
    "check_kill_lock",
    "clear_kill_lock",
    "db_mutex",
    "get_todays_realized_pnl",
    "persist_peak_price",
    "recover_peak_price",
]
