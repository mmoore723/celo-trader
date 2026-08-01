"""
trading/state/risk_log.py — per-user RiskManager instances and per-user
trade-scoped logger adapters.

Split out of the old single trading/state.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

import logging

from trading.state.constants import logger
from trading.state.locks import _default_user_id

# ── Per-user RiskManager instances (set in loop.py, read in entry.py) ────────
# FIX: this used to be a single module-level `_risk` global in trading/entry.py,
# overwritten by whichever user's bot started most recently — two users running
# concurrently would size and risk-gate trades using EACH OTHER's RiskManager
# (wrong account balance, wrong stop %, wrong daily-loss threshold). Now keyed
# per user, same pattern as _USER_STOP_EVENTS/_USER_LOCKS above.
_USER_RISK: dict[str, object] = {}   # type: dict[str, "RiskManager"]


def get_user_risk(user_id: str | None = None) -> object | None:
    """Return the given (or current) user's RiskManager instance, or None if
    their loop hasn't started one yet."""
    uid = user_id or _default_user_id()
    return _USER_RISK.get(uid)


def set_user_risk(risk_mgr: object, user_id: str | None = None) -> None:
    """Set the given (or current) user's RiskManager instance."""
    uid = user_id or _default_user_id()
    _USER_RISK[uid] = risk_mgr


# ── Per-user trade-scoped logger adapter ──────────────────────────────────────
# FIX: same shape of bug as _risk above, but for the contextual logger adapter
# bound while a trade is open (adds ticker/contract/trade-id context to every
# log line). Was a module-level `_trade_log` global in trading/entry.py,
# reassigned by whichever user's trade opened most recently — a second
# concurrent user's log lines could get tagged with the first user's trade
# context. Lower severity than _risk (only affects log readability, not order
# execution/sizing) but fixed the same way for consistency.
_USER_TRADE_LOG: dict[str, logging.Logger] = {}


def get_user_trade_log(user_id: str | None = None) -> logging.Logger:
    """Return the given (or current) user's trade-scoped logger, defaulting
    to the plain module logger if no trade is currently open for them."""
    uid = user_id or _default_user_id()
    return _USER_TRADE_LOG.get(uid, logger)


def set_user_trade_log(log: logging.Logger, user_id: str | None = None) -> None:
    """Set the given (or current) user's trade-scoped logger."""
    uid = user_id or _default_user_id()
    _USER_TRADE_LOG[uid] = log
