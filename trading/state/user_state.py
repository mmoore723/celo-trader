"""
trading/state/user_state.py — per-user live bot state dicts.

Split out of the old single trading/state.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

USER_STATES[user_id] holds each user's isolated state dict; get_user_state()
(optionally called with no argument) resolves the CURRENT user via the auth
ContextVar snapshot the calling thread was started with (see
_default_user_id in trading/state/locks.py), so any module that does
`_US = get_user_state()` gets that same live dict — mutations are
immediately visible everywhere else that resolves the same user_id. No
copies, no desync, and (unlike the old single-global-dict design) no
cross-user leakage either.

LIVE_STATE below is a backward-compat alias that ALWAYS points at the admin
user's dict specifically — nothing in this codebase should import it
directly anymore; it's kept only in case an external tool/script still
reaches for it directly.
"""

from datetime import datetime

from trading.state.constants import _ET_TZ, _DATA_GAP_WARN_MINUTES, _now_et, logger
from trading.state.locks import _default_user_id

from risk import RiskManager  # noqa: E402,F401
from config import _DEFAULTS  # noqa: E402


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
        # CLEANUP 2026-07-22 (full-audit finding 1.5): dashboard placeholder,
        # overwritten by the real synced value on the next tick — but read
        # from config's _DEFAULTS instead of RiskManager's raw class default
        # so it can't silently drift from the two if they're ever edited
        # separately.
        "current_stop_pct":      float(_DEFAULTS.get("orb_stop_loss_pct", 20)) / 100.0,
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
        # 2026-07-23 (Gap 3, professional-strategy-alignment audit): per-ticker
        # cache for the live 1Hour MTF confirmation gate — see
        # trading/mtf_live_gate.py. {ticker: {"ts": epoch, "price_above_ema20": bool}}
        "mtf_1h_cache":              {},
        # One causal 15-minute paper-research window.  It contains only
        # serializable metadata, never a live order or a signal object.
        "opportunity_scheduler":      {},
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
    # CLEANUP 2026-07-22 (full-audit finding 1.5) — see matching note above.
    _US["current_stop_pct"]       = float(_DEFAULTS.get("orb_stop_loss_pct", 20)) / 100.0
    _US["struct_stop_price"]      = None
    _US["scanner_ran_today"]      = False
    _US["scan_watchlist"]         = []
    _US["scan_idx"]               = 0
    _US["ticker_win_cooldown"]    = {}
    _US["orb_entered_today"]      = set()
    _US["_last_order_key"]        = None
    _US["opportunity_scheduler"]  = {}
    logger.info(
        "session_state_reset",
        extra={"event": "session_state_reset", "reason": "paper_trading_mode_toggle", "user_id": user_id},
    )
