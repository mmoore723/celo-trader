"""
trading/state.py — Per-user mutable state for the entire trading subsystem.

Every other trading/ module imports from here. USER_STATES[user_id] holds
each user's isolated state dict; get_user_state() (optionally called with
no argument) resolves the CURRENT user via the auth ContextVar snapshot the
calling thread was started with (see _default_user_id below), so any module
that does `_US = get_user_state()` gets that same live dict — mutations are
immediately visible everywhere else that resolves the same user_id. No
copies, no desync, and (unlike the old single-global-dict design) no
cross-user leakage either.

LIVE_STATE below is a backward-compat alias that ALWAYS points at the admin
user's dict specifically — nothing in this codebase should import it
directly anymore; it's kept only in case an external tool/script still
reaches for it directly.
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz as _pytz

# ── Project root — submodules in trading/ use this to write bot_state.json etc.
_BOT_ROOT = Path(__file__).resolve().parent.parent

# ── Timezone helper ───────────────────────────────────────────────────────────
_ET_TZ = _pytz.timezone("US/Eastern")


def _now_et() -> datetime:
    """Return the current wall-clock time as a tz-aware US/Eastern datetime."""
    return datetime.now(_ET_TZ)


# Network health watchdog constants
_DATA_GAP_WARN_MINUTES  = 5    # alert after this many minutes without a clean bar fetch
_DATA_GAP_PAUSE_MINUTES = 10   # skip strategy evaluation after this many minutes (stale data)

# ── Logger ────────────────────────────────────────────────────────────────────
logger = logging.getLogger("celo_trader.trading_logic")

# ── Per-user singleton guards ─────────────────────────────────────────────────
# Each user gets their own stop event and lock so multiple users can run
# concurrent bot instances without interfering.
# Legacy single-instance symbols (_stop_event, _bot_loop_lock) still refer
# to the "admin" user's state for backward-compat with existing import sites.

_USER_STOP_EVENTS: dict[str, threading.Event] = {}
_USER_LOCKS:       dict[str, threading.Lock]  = {}


def _get_stop_event(user_id: str = "admin") -> threading.Event:
    if user_id not in _USER_STOP_EVENTS:
        _USER_STOP_EVENTS[user_id] = threading.Event()
    return _USER_STOP_EVENTS[user_id]


def _get_lock(user_id: str = "admin") -> threading.Lock:
    if user_id not in _USER_LOCKS:
        _USER_LOCKS[user_id] = threading.Lock()
    return _USER_LOCKS[user_id]


# Backward-compat aliases — point to admin user's primitives
_stop_event    = _get_stop_event("admin")
_bot_loop_lock = _get_lock("admin")


def _default_user_id() -> str:
    """
    Resolve the calling user from the request-scoped ContextVar set by
    api/middleware/auth.py, falling back to "admin" for background-thread
    or single-user code paths where no request context exists.

    Background trading-loop threads are started via contextvars.copy_context()
    (see api/routes/bot.py::start_bot), which snapshots this ContextVar at
    thread-start time — so a call made from inside a user's own loop thread
    resolves to *that* user for the thread's entire lifetime, not whichever
    request happens to be in flight at the moment of the call.
    """
    try:
        from auth.context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return "admin"


# ── Per-user RiskManager instances (set in loop.py, read in entry.py) ────────
# FIX: this used to be a single module-level `_risk` global in trading/entry.py,
# overwritten by whichever user's bot started most recently — two users running
# concurrently would size and risk-gate trades using EACH OTHER's RiskManager
# (wrong account balance, wrong stop %, wrong daily-loss threshold). Now keyed
# per user, same pattern as _USER_STOP_EVENTS/_USER_LOCKS above.
_USER_RISK: dict[str, object] = {}   # type: dict[str, "RiskManager"]


def get_user_risk(user_id: str | None = None) -> Optional[object]:
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


# ── Per-user live state ────────────────────────────────────────────────────────
# USER_STATES[user_id] is each user's isolated bot state dict.
# LIVE_STATE is a backward-compat alias pointing to USER_STATES["admin"].
from risk import RiskManager  # noqa: E402


def _make_initial_state() -> dict:
    """Return a fresh state dict for a new user's bot instance."""
    return {
        "account_balance":      0.0,
        "options_buying_power": 0.0,
        "ghost_position_alert": None,
        "open_trade":      None,
        "open_trades":     [],
        "positions":       {},
        "last_signal":     None,
        "current_ticker":  None,
        "bars_5m":         [],
        "session_pnl":     0.0,
        "status":          "idle",
        "last_update":     None,
        "peak_price":      None,
        "last_tax_sweep":  0.0,
        "market_open":     False,
        "scan_watchlist":    [],
        "scan_idx":          0,
        "scanner_ran_today": False,
        "entry_time":            None,
        "stage1_done":           False,
        "stage1_be_price":       None,
        "orb_triggered":         False,
        "current_stop_pct":      RiskManager.ORB_STOP_PCT,
        "struct_stop_price":     None,
        "flip_eligible":         False,
        "flip_direction":        None,
        "flip_ticker":           None,
        "last_direction":        None,
        "last_trade_closed_time": None,
        "ticker_win_cooldown":   {},
        "orb_entered_today":     set(),
        "_last_order_key":       None,
        "last_eval_ticker":      None,
        "last_eval_opt_type":    None,
        "last_eval_premium":     None,
        "last_eval_eff_entry":   None,
        "last_eval_time":        None,
        "last_eval_expiry":      None,
        "last_eval_strike":      None,
        "last_eval_contract_symbol": None,
        "last_eval_contracts":   None,
        "risk_budget_usd":       0.0,
        "max_affordable_premium": 0.0,
        "last_successful_bar_fetch": None,
        "data_gap_minutes":          0,
    }


# Registry of all per-user state dicts
USER_STATES: dict[str, dict] = {}


def get_user_state(user_id: str | None = None) -> dict:
    """
    Return (creating if needed) the live state dict for a given user.

    FIX: user_id now defaults to the ContextVar-resolved current user (via
    _default_user_id()) instead of hardcoded "admin". This means any call
    site that does `get_user_state()` with no argument — from a request
    handler, or from inside a user's own copy_context()'d loop thread —
    automatically resolves to the correct user without needing user_id
    threaded through every intermediate function signature. Passing an
    explicit user_id still works exactly as before for callers that already
    have it in hand (e.g. api/routes/bot.py).
    """
    uid = user_id or _default_user_id()
    if uid not in USER_STATES:
        USER_STATES[uid] = _make_initial_state()
    return USER_STATES[uid]


# Backward-compat: LIVE_STATE always refers to the admin user's state.
# All existing modules that do `from trading.state import LIVE_STATE`
# continue to work without changes.
LIVE_STATE: dict = get_user_state("admin")




def _update_data_gap() -> None:
    """
    Called on every FAILED bar fetch.  Updates data_gap_minutes and emits a
    one-time warning the first time the gap crosses _DATA_GAP_WARN_MINUTES.

    FIX: previously read/wrote the global LIVE_STATE alias (admin's state)
    directly — every user's data-gap watchdog was tracking admin's bar-fetch
    history instead of their own. get_user_state() resolves fresh via the
    ContextVar snapshot the calling thread was started with, so this is
    correct regardless of which user's loop calls it (called from
    trading/entry.py::_tick(), which always runs inside the correct
    per-user thread).
    """
    # Defer database import to avoid heavy import at module load time
    from database import log_event
    _US = get_user_state()

    last_str = _US.get("last_successful_bar_fetch")
    if last_str is None:
        _US["last_successful_bar_fetch"] = _now_et().isoformat()
        _US["data_gap_minutes"] = 0
        return

    try:
        last_dt = datetime.fromisoformat(last_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=_ET_TZ)
        gap = int((_now_et() - last_dt).total_seconds() / 60)
    except Exception:
        gap = 0

    prev_gap = _US.get("data_gap_minutes", 0)
    _US["data_gap_minutes"] = gap

    if gap >= _DATA_GAP_WARN_MINUTES and prev_gap < _DATA_GAP_WARN_MINUTES:
        log_event("WARNING", "network_watchdog",
                  f"⚠️ No bar data received for {gap} minutes — bot is BLIND. "
                  f"Last clean fetch: {last_str[11:16]} ET. "
                  f"Check your internet connection or Alpaca's status page. "
                  f"Strategy evaluation is paused until data resumes.")
        logger.warning("Data gap watchdog: %d minutes without a clean bar fetch", gap)


def reset_session_state(user_id: str = "admin") -> None:
    """
    Hard-reset the given user's state and purge the SIM trade cache from
    session_state whenever the paper/live trading mode is toggled.

    FIX: previously hardcoded to the global LIVE_STATE alias (== admin's
    state) regardless of which user's "Reset Session" button was clicked —
    a non-admin user's reset silently reset the admin account instead of
    their own. Now resolves the caller's own state dict.
    """
    _US = get_user_state(user_id)
    _US["open_trade"]             = None
    _US["open_trades"]            = []
    _US["positions"]              = {}
    _US["session_pnl"]            = 0.0
    _US["status"]                 = "idle"
    _US["last_signal"]            = None
    _US["entry_time"]             = None
    _US["stage1_done"]            = False
    _US["stage1_be_price"]        = None
    _US["orb_triggered"]          = False
    _US["flip_eligible"]          = False
    _US["flip_direction"]         = None
    _US["flip_ticker"]            = None
    _US["last_direction"]         = None
    _US["last_trade_closed_time"] = None
    _US["peak_price"]             = None
    _US["current_stop_pct"]       = RiskManager.ORB_STOP_PCT
    _US["struct_stop_price"]      = None
    _US["scanner_ran_today"]      = False
    _US["scan_watchlist"]         = []
    _US["scan_idx"]               = 0
    _US["ticker_win_cooldown"]    = {}
    _US["orb_entered_today"]      = set()
    _US["_last_order_key"]        = None
    logger.info(
        "session_state_reset",
        extra={"event": "session_state_reset", "reason": "paper_trading_mode_toggle", "user_id": user_id},
    )
