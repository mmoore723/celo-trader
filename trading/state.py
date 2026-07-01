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

# ── Singleton / loop guards ───────────────────────────────────────────────────
_stop_event    = threading.Event()
_bot_loop_lock = threading.Lock()   # only one trading loop may run at a time

# ── RiskManager instance (set in loop.py, read everywhere) ───────────────────
# Imported lazily to avoid heavy circular imports at module load time.
_risk = None   # type: Optional[object]

# ── Shared state dict ─────────────────────────────────────────────────────────
# Import RiskManager here for the ORB_STOP_PCT class attribute used at init.
from risk import RiskManager  # noqa: E402

LIVE_STATE: dict = {
    "account_balance":      0.0,
    "options_buying_power": 0.0,
    "ghost_position_alert": None,
    "open_trade":      None,   # backward-compat: most-recently-opened of open_trades, or None
    "open_trades":     [],     # list of ALL open trade dicts (MAX_CONCURRENT_POSITIONS support)
    # Per-position live-management state, keyed by trade_id.  Replaces the
    # single-position fields that used to be overwritten in place.
    # Structure: { trade_id: {peak_price, stage1_done, stage1_be_price,
    #              current_stop_pct, struct_stop_price, current_option_price,
    #              current_option_price_time, entry_time,
    #              last_position_narration_minute} }
    "positions":       {},
    "last_signal":     None,
    "current_ticker":  None,
    "bars_5m":         [],
    "session_pnl":     0.0,
    "status":          "idle",
    "last_update":     None,
    "peak_price":      None,     # kept for DB compatibility
    "last_tax_sweep":  0.0,
    "market_open":     False,
    # ── Scanner watchlist state ───────────────────────────────────────────────
    "scan_watchlist":    [],
    "scan_idx":          0,
    "scanner_ran_today": False,
    # ── ORB-specific state ────────────────────────────────────────────────────
    "entry_time":            None,
    "stage1_done":           False,
    "stage1_be_price":       None,
    "orb_triggered":         False,
    "current_stop_pct":      RiskManager.ORB_STOP_PCT,
    "struct_stop_price":     None,
    # ── Flip-trade state ─────────────────────────────────────────────────────
    "flip_eligible":         False,
    "flip_direction":        None,
    "flip_ticker":           None,
    "last_direction":        None,
    "last_trade_closed_time": None,
    # ── Per-session entry guards ──────────────────────────────────────────────
    "ticker_win_cooldown":   {},
    "orb_entered_today":     set(),
    # ── Duplicate-order guard ─────────────────────────────────────────────────
    "_last_order_key":       None,
    # ── Sizing / affordability state ──────────────────────────────────────────
    "last_eval_ticker":      None,
    "last_eval_opt_type":    None,
    "last_eval_premium":     None,
    "last_eval_eff_entry":   None,
    "last_eval_time":        None,
    "last_eval_expiry":      None,
    "last_eval_strike":      None,
    "last_eval_contract_symbol": None,
    "last_eval_contracts":   None,   # number of contracts sized for this eval
    "risk_budget_usd":       0.0,
    "max_affordable_premium": 0.0,
    # ── Network health watchdog ───────────────────────────────────────────────
    "last_successful_bar_fetch": None,
    "data_gap_minutes":          0,
}


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
