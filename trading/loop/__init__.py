"""
trading/loop/__init__.py — Re-exports the old trading/loop.py's public
surface (run_trading_loop, stop_loop, _sleep_until_next_day) plus the
inner/helper functions, so every existing `from trading.loop import X`
call site across the app keeps working unchanged.

Split out of the old single trading/loop.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from trading.loop.lifecycle import run_trading_loop, stop_loop, _sleep_until_next_day
from trading.loop.inner import _run_trading_loop_inner
from trading.loop.audits import (
    _run_nightly_strategy_audit_once,
    _run_nightly_ticker_qualification_once,
    _run_weekly_strategy_review_once,
)

__all__ = [
    "run_trading_loop", "stop_loop", "_sleep_until_next_day",
    "_run_trading_loop_inner",
    "_run_nightly_strategy_audit_once", "_run_nightly_ticker_qualification_once",
    "_run_weekly_strategy_review_once",
]
