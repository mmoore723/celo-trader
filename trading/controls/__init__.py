"""
trading/controls/__init__.py — Manual and emergency position control
functions.

Functions:
  close_trade_by_id         — per-row journal close (Trade Journal button)
  manual_close_position     — closes all open positions (dashboard button)
  panic_close_all           — emergency flatten (public API)
  _panic_close_all_positions — internal variant called by kill-lock handler

Split (2026-08-01, file-size cleanup) out of the old single
trading/controls.py into helpers.py, journal_close.py, manual_close.py,
and panic.py; no logic changed, only relocated. Re-exports every public
name so every existing `from trading.controls import X` call site across
the app keeps working unchanged.
"""

from __future__ import annotations

from trading.controls.helpers import _default_user_id, _refresh_session_pnl
from trading.controls.journal_close import close_trade_by_id
from trading.controls.manual_close import manual_close_position
from trading.controls.panic import panic_close_all, _panic_close_all_positions

__all__ = [
    "_default_user_id", "_refresh_session_pnl",
    "close_trade_by_id",
    "manual_close_position",
    "panic_close_all", "_panic_close_all_positions",
]
