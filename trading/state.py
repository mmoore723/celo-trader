"""
trading/state.py — Shared mutable state for the entire trading subsystem.

Every other trading/ module imports from here.  Using a single module-level
dict (LIVE_STATE) means all sub-modules that do
    from trading.state import LIVE_STATE
receive the SAME dict object — mutations in one module are immediately
visible everywhere else.  No copies, no desync.
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

# ── RiskManager instance (set in loop.py, read everywhere) ───────────────────
# Imported lazily to avoid heavy circular imports at module load time.
_risk = None   # type: Optional[object]

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


def get_user_state(user_id: str = "admin") -> dict:
    """Return (creating if needed) the live state dict for a given user."""
    if user_id not in USER_STATES:
        USER_STATES[user_id] = _make_initial_state()
    return USER_STATES[user_id]


# Backward-compat: LIVE_STATE always refers to the admin user's state.
# All existing modules that do `from trading.state import LIVE_STATE`
# continue to work without changes.
LIVE_STATE: dict = get_user_state("admin")




def _update_data_gap() -> None:
    """
    Called on every FAILED bar fetch.  Updates data_gap_minutes and emits a
    one-time warning the first time the gap crosses _DATA_GAP_WARN_MINUTES.
    """
    # Defer database import to avoid heavy import at module load time
    from database import log_event

    last_str = LIVE_STATE.get("last_successful_bar_fetch")
    if last_str is None:
        LIVE_STATE["last_successful_bar_fetch"] = _now_et().isoformat()
        LIVE_STATE["data_gap_minutes"] = 0
        return

    try:
        last_dt = datetime.fromisoformat(last_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=_ET_TZ)
        gap = int((_now_et() - last_dt).total_seconds() / 60)
    except Exception:
        gap = 0

    prev_gap = LIVE_STATE.get("data_gap_minutes", 0)
    LIVE_STATE["data_gap_minutes"] = gap

    if gap >= _DATA_GAP_WARN_MINUTES and prev_gap < _DATA_GAP_WARN_MINUTES:
        log_event("WARNING", "network_watchdog",
                  f"⚠️ No bar data received for {gap} minutes — bot is BLIND. "
                  f"Last clean fetch: {last_str[11:16]} ET. "
                  f"Check your internet connection or Alpaca's status page. "
                  f"Strategy evaluation is paused until data resumes.")
        logger.warning("Data gap watchdog: %d minutes without a clean bar fetch", gap)


def reset_session_state() -> None:
    """
    Hard-reset LIVE_STATE and purge the SIM trade cache from session_state
    whenever the paper/live trading mode is toggled.
    """
    LIVE_STATE["open_trade"]             = None
    LIVE_STATE["open_trades"]            = []
    LIVE_STATE["positions"]              = {}
    LIVE_STATE["session_pnl"]            = 0.0
    LIVE_STATE["status"]                 = "idle"
    LIVE_STATE["last_signal"]            = None
    LIVE_STATE["entry_time"]             = None
    LIVE_STATE["stage1_done"]            = False
    LIVE_STATE["stage1_be_price"]        = None
    LIVE_STATE["orb_triggered"]          = False
    LIVE_STATE["flip_eligible"]          = False
    LIVE_STATE["flip_direction"]         = None
    LIVE_STATE["flip_ticker"]            = None
    LIVE_STATE["last_direction"]         = None
    LIVE_STATE["last_trade_closed_time"] = None
    LIVE_STATE["peak_price"]             = None
    LIVE_STATE["current_stop_pct"]       = RiskManager.ORB_STOP_PCT
    LIVE_STATE["struct_stop_price"]      = None
    LIVE_STATE["scanner_ran_today"]      = False
    LIVE_STATE["scan_watchlist"]         = []
    LIVE_STATE["scan_idx"]               = 0
    LIVE_STATE["ticker_win_cooldown"]    = {}
    LIVE_STATE["orb_entered_today"]      = set()
    LIVE_STATE["_last_order_key"]        = None
    logger.info(
        "session_state_reset",
        extra={"event": "session_state_reset", "reason": "paper_trading_mode_toggle"},
    )
