"""
trading/entry/tick.py — The main per-tick evaluation.

Split out of trading/entry.py (2026-08-01, file-size cleanup); _tick()
itself is left as ONE function, internally UNCHANGED -- it's a single
sequential live order-placement pipeline (session reset -> market hours
check -> balance -> position management -> ticker selection -> signal
routing -> gates -> contract selection -> sizing -> order placement -> DB
recording) built on a long chain of local variables that later phases
read. Splitting its BODY across files would mean redesigning an internal
parameter-passing contract between phases on the highest-stakes function in
the app -- a rewrite disguised as a reorganization. Every other file in
this cleanup pass keeps whole, single, sequential functions like this
together for the same reason -- see risk/exits.py and
trading/position_manager/manage.py + close.py for the same documented
exception.
"""

from __future__ import annotations

# ── __file__ redirect ──────────────────────────────────────────────────
# Must happen BEFORE any Path(__file__) usage anywhere in this module.
# This file now lives one level deeper than the original (trading/entry/
# tick.py vs trading/entry.py), so the fix needs one more dirname() call
# than the original did.
import os as _os_file_fix
__file__ = _os_file_fix.path.join(
    _os_file_fix.path.dirname(_os_file_fix.path.dirname(_os_file_fix.path.dirname(_os_file_fix.path.abspath(__file__)))),
    _os_file_fix.path.basename(__file__)
)
del _os_file_fix

import logging
import time
import threading
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Tuple
from uuid import uuid4

import pandas as pd
import pytz as _pytz

# ── Project imports ──────────────────────────────────────────────────────
from config import (
    TRADIER_ACCOUNT_ID,
    LIQUID_TICKERS,
    STARTING_CAPITAL,
    MIN_CONTRACT_COST, MAX_CONTRACT_COST, MIN_OPEN_INTEREST,
    EARNINGS_BLACKOUT_DAYS,
    get_settings, get_risk_tier,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT as _GMT_TL, MID_TIER_RISK_PCT as _MTT_TL,
    MAX_CONCURRENT_POSITIONS,
    SESSION_HARD_CUTOFF_HM,
    STAGE2_TRAIL_PCT,
    get_bot_state_path,
    atomic_write_json, atomic_update_json,
)
from broker import AlpacaClient, TradierClient, get_clients
from signals import (
    bars_to_df, relative_volume_rank, is_near_earnings,
    detect_orb_breakout,
)
from strategy_router import route_signals, Signal as _RouterSignal
from risk import (
    RiskManager, DailyLossLimitReached,
    persist_peak_price, recover_peak_price,
    set_kill_lock, check_kill_lock,
)
from scanner import run_scan, get_watchlist, is_premarket_window, is_scan_window
from database import (
    init_db, insert_trade, close_trade, get_open_trade, get_open_trades,
    log_event, get_all_trades, get_conn,
)
from signal_journal import log_signal_outcome as _log_journal
from alerts import send_alert
from tax_engine import record_sweep


def _confirmed_entry_price(order: dict, fallback_ask: float) -> float:
    """Return the broker's actual entry fill before any planned quote fallback."""
    return float(
        order.get("confirmed_fill_price")
        or order.get("filled_avg_price")
        or fallback_ask
    )


def _entry_order_wait_seconds(*, has_open_positions: bool) -> int:
    """Bound entry patience without starving existing-position exits.

    The scanner and position manager share one per-user loop.  A long,
    synchronous entry wait is acceptable while flat, but while another trade
    is open it would postpone stop/trailing-exit evaluation.  Give a flat
    account most of the next one-minute candle; otherwise return control after
    ten seconds so the next management pass happens promptly.
    """
    return 10 if has_open_positions else 45


def _entry_quote_is_fresh(quote: dict | None, maximum_age_seconds: float = 120.0) -> bool:
    """Fail closed when an executable quote has no broker timestamp or is delayed."""
    if not quote:
        return False
    try:
        age = quote.get("quote_age_seconds")
        return age is not None and 0 <= float(age) <= float(maximum_age_seconds)
    except (TypeError, ValueError):
        return False

# ── State / shared globals (from state.py) ────────────────────────────────
from trading.state import (
    get_user_state, get_user_risk, get_user_trade_log, set_user_trade_log,
    _now_et, _ET_TZ,
    _DATA_GAP_WARN_MINUTES, _DATA_GAP_PAUSE_MINUTES, _update_data_gap,
)

# ── Sibling job imports ────────────────────────────────────────────────────
from trading.diagnostics import _log_bar_thinking, _check_ghost_positions, _sweep_orphaned_orders
from trading.position_manager import _manage_open_position, _close_position

# ── Split-out entry helpers (2026-08-01) ───────────────────────────────────
from trading.entry.contract import select_contract, select_reviewed_v2_contract
from trading.v2_orb_paper_execution import entry_limit_prices, include_reviewed_tickers_when_v2_pilots_enabled
from trading.v2_orb_execution_profile import (
    uses_reviewed_paid_execution_profile,
    uses_v2_orb_execution_profile,
)
from trading.orb_retouch_execution import update_one_minute_orb_retouch
from trading.two_leg_trend_pullback_execution import update_two_leg_trend_pullback
from trading.entry.skip_log import _skip_log
from trading.opportunity_scheduler import clear as _clear_opportunity_window
from trading.opportunity_scheduler import due_ticker as _opportunity_due_ticker
from trading.opportunity_scheduler import select as _select_opportunity_signal

logger = logging.getLogger("celo_trader.trading_logic")

# NOTE: _trade_log / _risk module-level globals were removed in a prior
# session — see trading.state.get_user_trade_log()/get_user_risk(). _tick()
# resolves both fresh each call instead of reading module globals.


# ── Per-tick evaluation ───────────────────────────────────────────────────────

def _tick(alpaca: AlpacaClient, tradier: TradierClient, *,
          scan_ticker: str | None = None, execution_only: bool = False) -> None:
    # FIX: _risk used to be a `global _risk` module attribute in this file,
    # set once by loop.py (`_em._risk = RiskManager(...)`) — shared by every
    # user's thread. Two users' bots running at once would size/risk-gate
    # trades using WHICHEVER user's RiskManager was set most recently. _US
    # was the equivalent bug for LIVE_STATE. Both are now resolved fresh each
    # tick via the ContextVar snapshot each user's loop thread was started
    # with (see trading/state.py::_default_user_id), so this function is
    # correct regardless of how many users' loops are running concurrently.
    _US   = get_user_state()
    _risk = get_user_risk()
    # This is an execution boundary, not merely a UI flag.  Collection-only
    # maintenance is allowed to reach the router/quote recorder below, but it
    # must never manage positions, cancel orders, or submit an entry.
    from config import get_maintenance_state
    _maintenance = get_maintenance_state()
    collection_only = bool(
        _maintenance.get("maintenance_mode", False)
        and _maintenance.get("collection_only", False)
    )

    # ── CRITICAL: ticker and status must be initialized before ANY branch ─────
    # Python treats any variable assigned ANYWHERE in a function as local
    # throughout the entire scope. Without this plain assignment first, every
    ticker = None                          # overwritten at ticker-selection block
    _US["status"] = "scanning"      # reset here so bot_state.json write
    # below never lags with a stale "standby" value from the previous tick.
    _US["last_update"] = _now_et().isoformat()

    # ── Daily session reset ───────────────────────────────────────────────────
    # If the calendar date has changed since the last tick, reset session P&L
    # Reset to 0 and recalculate from today's closed trades only.
    _today_str = _now_et().date().isoformat()
    if _US.get("_session_date") != _today_str:
        _US["_session_date"]      = _today_str
        _US["session_pnl"]        = 0.0
        _US["scanner_ran_today"]  = False
        _US["orb_entered_today"]  = set()
        _US["ticker_win_cooldown"] = {}
        _US["opportunity_scheduler"] = {}
        # Recalculate from DB in case trades were closed earlier today
        from trading.controls import _refresh_session_pnl
        _refresh_session_pnl()
        log_event("INFO", "session",
                  f"📅 New trading day ({_today_str}) — session P&L reset to $0.")

    # ── FIX S6: Market hours check ────────────────────────────────────────────
    # Write heartbeat so dashboard can detect the bot is running
    import pathlib as _pl, time as _tm
    _hb = _pl.Path(__file__).parent / ".bot_heartbeat"
    _hb.write_text(str(_tm.time()))

    # Fast local time check BEFORE any Alpaca API call.
    # Outside extended hours (8 PM - 4 AM ET), skip the market-status call.
    _now_local = _now_et()
    _hm_local  = _now_local.hour * 60 + _now_local.minute
    _is_weekend = _now_local.weekday() >= 5   # Saturday=5, Sunday=6
    _extended_hours = 4 * 60 <= _hm_local < 20 * 60  # 4 AM – 8 PM ET
    if _is_weekend or not _extended_hours:
        # Definitely closed — no need to call Alpaca
        market_open = False
        _US["market_open"] = False
    else:
        market_open = alpaca.is_market_open()
        _US["market_open"] = market_open

    # Always write state so dashboard knows bot is alive even when market closed
    import json as _json, time as _time
    _state_path = get_bot_state_path()

    if not market_open:
        # Broker/calendar truth is authoritative. Never turn a False into
        # True from wall-clock time: holidays and emergency closures occur
        # during ordinary weekday session hours.
        _US["status"] = "market_closed"
        _US["orb_triggered"]     = False
        _US["flip_eligible"]     = False
        _US["flip_direction"]    = None
        _US["flip_ticker"]       = None
        _US["scanner_ran_today"] = False   # allow fresh scan tomorrow
        _US["scan_watchlist"]    = []
        _US["scan_idx"]          = 0
        _US["opportunity_scheduler"] = {}
        logger.debug("Market closed — session flags reset for tomorrow")
        try:
            _mc_balance = (_US.get("account_balance") or
                           get_settings().get("last_known_balance", STARTING_CAPITAL))
            atomic_write_json(_state_path, {
                    "running":                True,
                    "account_balance":        _mc_balance,
                    "options_buying_power":   _US.get("options_buying_power", 0),
                    "ghost_position_alert":   _US.get("ghost_position_alert"),
                    "session_pnl":            _US.get("session_pnl", 0),
                    "status":                 "market_closed",
                    "current_ticker":         None,
                    "last_signal":            None,
                    "market_open":            False,
                    "last_update":            _time.strftime("%H:%M:%S"),
                    "entry_time":             None,
                    "stage1_done":            False,
                    "orb_triggered":          False,
                    # CLEANUP 2026-07-22 (full-audit finding 1.6): 0.30 was the
                    # pre-2026-07-18 stop value, stale vs. today's 0.20 — only
                    # fires when _risk isn't initialized yet (dashboard display
                    # only, no trading impact), but no reason to leave it wrong.
                    "current_stop_pct":       _risk.ORB_STOP_PCT if _risk else float(get_settings().get("orb_stop_loss_pct", 20)) / 100.0,
                    "flip_eligible":          False,
                    "flip_direction":         None,
                    "flip_ticker":            None,
                    "last_direction":         _US.get("last_direction"),
                    "last_trade_closed_time": _US.get("last_trade_closed_time"),
                    "network_ok":             _US.get("network_ok", True),
                    "risk_budget_usd":        round(_mc_balance * _risk.effective_risk_pct(_mc_balance), 2) if _risk else 0.0,
                    "max_affordable_premium": _risk.max_affordable_premium(_mc_balance) if _risk else 0.0,
                    "last_eval_ticker":       _US.get("last_eval_ticker"),
                    "last_eval_opt_type":     _US.get("last_eval_opt_type"),
                    "last_eval_premium":      _US.get("last_eval_premium"),
                    "last_eval_eff_entry":    _US.get("last_eval_eff_entry"),
                    "last_eval_time":         _US.get("last_eval_time"),
                    "last_eval_expiry":       _US.get("last_eval_expiry"),
                    "last_eval_strike":       _US.get("last_eval_strike"),
                    "current_option_price":      _US.get("current_option_price"),
                    "current_option_price_time": _US.get("current_option_price_time"),
            })
        except Exception:
            pass
        return

    # ── Account balance ───────────────────────────────────────────────────────
    from broker import _cb_is_open as _alpaca_circuit_open
    try:
        acct    = alpaca.get_account()
        balance = float(acct.get("equity", 0)) if acct else 0
        if balance <= 0:
            balance = float(get_settings().get("last_known_balance", STARTING_CAPITAL))
            logger.warning("Account fetch returned empty — using last known $%.2f", balance)
        else:
            from config import save_settings as _save
            _save({"last_known_balance": round(balance, 2)})
        _US["account_balance"] = balance
        _US["network_ok"]      = True
        # FIX: capture Alpaca's options buying power so the dashboard can show
        # it on the Live Trading page and orders that are about to be rejected
        # for "insufficient options buying power" aren't a total surprise.
        _US["options_buying_power"] = (
            float(acct.get("options_buying_power", 0)) if acct
            else _US.get("options_buying_power", 0)
        )
    except Exception as e:
        logger.error("Balance fetch failed: %s — using last known balance", e)
        balance = float(get_settings().get("last_known_balance", STARTING_CAPITAL))
        _US["account_balance"] = balance
        _US["network_ok"]      = not _alpaca_circuit_open()

    # ── Reconciliation: catch positions Alpaca holds that the bot doesn't know
    # about (see _check_ghost_positions docstring for the 2026-06-15 incident
    # that motivated this). Stored in _US so the market-closed branch
    _US["ghost_position_alert"] = _check_ghost_positions(alpaca)
    from trading.recovery_state import restore_entries
    restore_entries(_US, get_settings().get("active_broker_account_id"), _now_et().date().isoformat())

    # ── Write shared state file so dashboard reads live bot state ─────────────
    from config import get_risk_tier as _grt, DAILY_LOSS_HARD_CAP_PCT as _DLHCP_FALLBACK, get_settings as _gs
    _kill_locked, _kill_reason = check_kill_lock()
    _is_paper = _gs().get("paper_trading", True)
    # 2026-07-24: this used to always show the hardcoded 10% constant even
    # after the hard cap became user-configurable (see risk.py) — dashboard
    # would silently lie about the real threshold once someone changed it.
    _DLHCP = _gs().get("daily_loss_hard_cap_pct", _DLHCP_FALLBACK * 100) / 100.0
    # Preserve eval_log across ticks using _US (in-memory).
    # File-read was racy: an intermediate write at line ~1133 could put
    _preserved_eval_log = _US.get("eval_log", [])
    try:
        atomic_write_json(_state_path, {
            "running":                True,
            "mode":                   "paper" if _is_paper else "live",
            "account_balance":        _US.get("account_balance", 0),
            "options_buying_power":   _US.get("options_buying_power", 0),
            "ghost_position_alert":   _US.get("ghost_position_alert"),
            "session_pnl":            _US.get("session_pnl", 0),
            "status":                 _US.get("status", "idle"),
            "current_ticker":         _US.get("current_ticker"),
            "last_signal":            _US.get("last_signal"),
            "last_strategy_id":       _US.get("last_strategy_id"),
            "market_open":            _US.get("market_open", False),
            "last_update":            _time.strftime("%H:%M:%S"),
            # ORB-specific fields — dashboard 45-min countdown & stop display
            "entry_time":             _US.get("entry_time"),
            "stage1_done":            _US.get("stage1_done", False),
            "stage1_be_price":        _US.get("stage1_be_price"),
            "orb_triggered":          _US.get("orb_triggered", False),
            "current_stop_pct":       _US.get("current_stop_pct", _risk.ORB_STOP_PCT if _risk else 0.30),
            # Flip-trade fields
            "flip_eligible":          _US.get("flip_eligible", False),
            "flip_direction":         _US.get("flip_direction"),
            "last_direction":         _US.get("last_direction"),
            "last_trade_closed_time": _US.get("last_trade_closed_time"),
            # Scanner fields — visible in dashboard
            "scan_watchlist":         _US.get("scan_watchlist", []),
            "current_scan_idx":       _US.get("scan_idx", 0),
            # Growth mode / risk tier
            "risk_pct":               _grt(balance),
            "growth_mode":            _grt(balance) > 0.01,
            "daily_loss_hard_cap":    _DLHCP,
            # Kill lock
            "kill_locked":            _kill_locked,
            "kill_lock_reason":       _kill_reason,
            # Network health — False when Alpaca circuit breaker is open
            "network_ok":             _US.get("network_ok", True),
            # Data-gap watchdog — how long (minutes) since the last clean bar fetch.
            # 0 = healthy.  ≥5 = bot was blind; dashboard shows a warning banner.
            "data_gap_minutes":          _US.get("data_gap_minutes", 0),
            "last_successful_bar_fetch": _US.get("last_successful_bar_fetch"),
            # ── Risk-sizing visibility ────────────────────────────────────────
            # risk_budget_usd:        $ the bot will lose if the 30% stop hits
            #                         on 1 contract (balance x effective_risk_pct).
            "risk_budget_usd":        round(balance * _risk.effective_risk_pct(balance), 2) if _risk else 0.0,
            "max_affordable_premium": _risk.max_affordable_premium(balance) if _risk else 0.0,
            # Most recently evaluated contract (set when the bot looks at a
            # specific option to size/enter — persists until the next evaluation).
            "last_eval_ticker":       _US.get("last_eval_ticker"),
            "last_eval_opt_type":     _US.get("last_eval_opt_type"),
            "last_eval_premium":      _US.get("last_eval_premium"),
            "last_eval_eff_entry":    _US.get("last_eval_eff_entry"),
            "last_eval_time":         _US.get("last_eval_time"),
            "last_eval_expiry":       _US.get("last_eval_expiry"),
            "last_eval_strike":       _US.get("last_eval_strike"),
            # Persist eval_log across ticks — wiped every tick otherwise
            "eval_log":               _preserved_eval_log,
        })
    except Exception:
        pass

    # ── Manage existing position(s) ────────────────────────────────────────────
    # NEW (MAX_CONCURRENT_POSITIONS): manage ALL open trades (up to the limit),
    # not just a single one. The orphaned-order sweep runs first so any resting
    # ── 3:55 PM ET hard session cutoff ───────────────────────────────────────
    # SESSION_HARD_CUTOFF_HM = (15, 55) from config.
    _et_now_cut = _now_et()
    _cutoff_minutes = SESSION_HARD_CUTOFF_HM[0] * 60 + SESSION_HARD_CUTOFF_HM[1]
    _now_minutes    = _et_now_cut.hour * 60 + _et_now_cut.minute
    if _now_minutes >= _cutoff_minutes and not collection_only:
        try:
            # Cancel any pending/working orders first to avoid orphaned fills
            _pending = alpaca.get_open_orders() or []
            for _ord in _pending:
                try:
                    alpaca.cancel_order(_ord.get("id", ""))
                    logger.info("session_cutoff_cancel_order id=%s", _ord.get("id"))
                except Exception as _ce:
                    logger.warning("Cutoff: failed to cancel order %s: %s", _ord.get("id"), _ce)

            # Force-close ALL open positions, including RECOVERED_UNTRACKED ones.
            #
            # FIX 2026-07-20: RECOVERED_UNTRACKED positions (ghost positions
            # auto-adopted from Alpaca by trading/diagnostics.py) are still
            # correctly excluded from the normal per-tick _manage_open_position
            # loop below — their fake entry_time (set to recovery time, not
            # real entry time) would misfire time-based stop/time-box logic.
            # But that reasoning doesn't apply here: the 3:55pm cutoff doesn't
            # use entry_time at all, it just flattens everything to avoid
            # after-hours exposure. Previously this loop skipped them entirely,
            # so once a position got auto-adopted it would NEVER close
            # automatically — not from a stop, not from a time cap, not even
            # at end of day — leaving it open indefinitely until someone
            # manually clicked "Close" in the Trade Journal.
            _cutoff_trades = get_open_trades()
            for _ct in _cutoff_trades:
                try:
                    _cq  = tradier.get_option_quote(_ct.get("contract_symbol", ""))
                    _cx  = _cq.get("mid", _ct.get("entry_price", 0)) if _cq else _ct.get("entry_price", 0)
                    _cbid = float(_cq.get("bid") or _cx) if _cq else None
                    _close_position(alpaca, _ct, _cx, "session_hard_cutoff_355pm",
                                    bid_price=_cbid, reference_quote=_cq)
                    log_event("WARNING", "trading_logic",
                              f"🔴 [{_ct.get('ticker')}] 3:55 PM hard cutoff — "
                              f"force-closing position to avoid after-hours exposure.")
                except Exception as _ex:
                    logger.error("Cutoff: failed to close trade %s: %s", _ct.get("id"), _ex)
        except Exception as _cut_ex:
            logger.error("Session cutoff sweep failed: %s", _cut_ex)

        _US["status"] = "session_cutoff"
        return   # no new entries after 3:55 PM

    open_trades = get_open_trades()
    _US["open_trades"] = open_trades

    # ── RECOVERED_UNTRACKED positions are now FULLY managed, same as everything
    # else ─────────────────────────────────────────────────────────────────
    # FIX 2026-07-20: the 2026-06-15 fix excluded recovered/ghost positions
    # from _manage_open_position entirely — no stop-loss, no time-cap, no
    # stage-1 profit-take, and (separately) no EOD flatten — because their
    # entry_time is set to the moment they were recovered, not their real
    # entry time, which would throw off time-based exits. But these are REAL
    # money-affecting positions, not test data, and "no automated risk
    # management at all" is a much worse outcome than "the time-cap clock
    # starts a bit late." Price-based stops (structural/ATR trail) don't
    # depend on entry_time at all, so they work correctly from the first
    # tick regardless. They also used to get a bespoke price-only update
    # written to a separate JSON file instead of the normal in-memory
    # position state the dashboard actually reads from — which is why they
    # showed "—" for live price/P&L instead of real numbers. Folding them
    # into the standard loop fixes both problems at once.
    #
    # RECOVERED_UNTRACKED trades still don't count against the
    # MAX_CONCURRENT_POSITIONS entry gate below (they weren't opened by that
    # gate's own logic — see database.py::get_open_trades()), so `_bot_trades`
    # is kept for that count, but the management loop now runs over EVERY
    # open trade.
    _bot_trades = [t for t in open_trades if t.get("strategy_id") != "RECOVERED_UNTRACKED"]
    _US["open_trade"] = open_trades[0] if open_trades else None

    if not collection_only:
        _sweep_orphaned_orders(alpaca, _bot_trades)
        for _open_trade in open_trades:
            _manage_open_position(alpaca, tradier, _open_trade, balance)
    else:
        _US["status"] = "collecting_data"

    settings = get_settings()
    # This value is needed by the router-observation lane below, long before
    # order placement.  Keep one source of truth for the whole tick so paper
    # evidence collection cannot crash before candidates are recorded.
    paper = bool(settings.get("paper_trading", True))
    if scan_ticker == "":
        _US["status"] = "in_trade" if open_trades else "standby"
        return  # Management-only pass when no strategy/ticker can enter.
    try:
        _max_positions = max(1, min(5, int(settings.get(
            "max_concurrent_positions", MAX_CONCURRENT_POSITIONS))))
    except (TypeError, ValueError):
        _max_positions = MAX_CONCURRENT_POSITIONS

    if len(_bot_trades) >= _max_positions and not collection_only:
        # All position slots are full — nothing left to do this tick except
        # manage the existing position(s) above.
        _US["status"] = "in_trade"
        return

    # ── Pre-trade gate ─────────────────────────────────────────────────────────
    # NEW (MAX_CONCURRENT_POSITIONS): if a slot is free but the bot is still
    # If holding a position in the OTHER slot, still reflect "in_trade".
    _US["status"] = "in_trade" if _bot_trades else "scanning"
    # ── Sync user-editable trade parameters into the live risk manager ────────
    # This runs every tick so settings changes take effect within seconds,
    # no bot restart needed.
    if _risk:
        _risk.ORB_STAGE1_GAIN = float(settings.get("orb_stage1_gain_pct", 50)) / 100.0
        _risk.ORB_STOP_PCT    = float(settings.get("orb_stop_loss_pct",   20)) / 100.0
        # Dynamic stage1 trigger overrides (2026-07-21) — same sync-every-tick
        # pattern as the two lines above, so Settings changes take effect
        # within seconds without a bot restart.
        _risk.STAGE1_DYNAMIC_ENABLED     = bool(settings.get("stage1_dynamic_enabled", True))
        _risk.STAGE1_ATR_TARGET_MULT     = float(settings.get("stage1_atr_target_mult", 2.0))
        _risk.STAGE1_FLOOR_FRACTION_OF_TARGET = float(settings.get("stage1_floor_fraction_of_target", 75)) / 100.0
        _risk.STAGE1_RVOL_FADE_THRESHOLD = float(settings.get("stage1_rvol_fade_threshold", 1.0))
        _risk.STAGE1_MOMENTUM_REQUIRE_BOTH = bool(settings.get("stage1_momentum_require_both", True))

    # Pass ET time explicitly — risk.py's is_trading_window() defaults to
    # datetime.now() which is UTC on EC2, making the 9:30–16:00 ET window
    allowed, reason = _risk.can_trade(balance, has_open_position=False, now=_now_et())
    if collection_only:
        # Continue to route and record candidates, even if live-entry guards
        # would have blocked an order.  The authoritative intent does not exist
        # yet; it is resolved at the later collection-only execution gate.
        allowed, reason = True, "maintenance_collection_only"
    if not allowed:
        logger.debug("Trading blocked: %s", reason)
        if "limit" in reason.lower() or "kill" in reason.lower():
            _US["status"] = "halted"
        elif "window" in reason.lower():
            # Show a specific standby state so the UI doesn't claim "idle" while
            # the bot is actually alive and waiting for the next session window.
            _US["status"] = "standby"
        else:
            _US["status"] = "idle"
        # Translate the internal reason code into a human-readable message
        _r = reason.lower()
        if "kill" in _r or "kill_lock" in _r:
            _gate_msg = "🔴 Daily loss limit hit — trading is paused for 24 hours."
        elif "daily loss" in _r or "daily_loss" in _r:
            _gate_msg = "🔴 Daily loss limit reached. No more trades today."
        elif "window" in _r or "outside" in _r:
            _gate_msg = "🟡 Outside trading hours. Bot is standing by."
        elif "balance" in _r or "capital" in _r:
            _gate_msg = "🔴 Account balance too low to size a trade safely."
        elif "open" in _r and "trade" in _r:
            _gate_msg = "🟡 Already in a trade — monitoring current position."
        elif "orb_triggered" in _r or "already triggered" in _r:
            _gate_msg = "🟡 Entry already taken today. Waiting for flip setup or next session."
        else:
            # NOTE: `ticker` is not yet assigned at this point in the function
            # (ticker selection happens further below) — referencing it here
            # raised UnboundLocalError 122x on 06-10 and crash-looped the bot
            # for ~3.5 hours. Use a generic message instead.
            _gate_msg = f"🟡 Skipping — {reason}"
        log_event("INFO", "bar_eval", _gate_msg)
        return

    # ── Ticker selection — cycle through scan watchlist ───────────────────────
    # The watchlist is populated by the pre-market scan (or on-demand below).
    # Each tick advances to the next ticker; the bot evaluates each for an ORB
    from scanner import TICKER_BLACKLIST as _BL
    watchlist = [t for t in (_US.get("scan_watchlist") or []) if t not in _BL]

    # The scanner stays broad.  Reviewed strategy/ticker pairs are appended
    # only when their own mode-eligible switch is enabled, so a quieter validated
    # symbol is not silently skipped by a momentum ranking.
    from config.strategy_catalog import (
        enabled_observation_strategy_ids, enabled_reviewed_strategy_ids,
    )
    _enabled_reviewed_pilots = enabled_reviewed_strategy_ids(
        settings, paper=bool(settings.get("paper_trading", True)),
    )
    _enabled_research_observers = enabled_observation_strategy_ids(settings)
    if not watchlist:
        # Watchlist empty: run an on-demand scan (missed pre-market, or first boot)
        try:
            watchlist = run_scan(alpaca, max_tickers=10)
        except Exception:
            watchlist = get_watchlist()  # read from disk; falls back to SPY/QQQ
        if not watchlist:
            watchlist = ["SPY", "QQQ"]
        _US["scan_watchlist"]    = watchlist
        _US["scan_idx"]          = 0
        _US["scanner_ran_today"] = True
        logger.info("on_demand_scan_done", extra={
            "event": "on_demand_scan_done", "watchlist": watchlist,
        })
    if _enabled_reviewed_pilots or _enabled_research_observers:
        _with_reviewed = include_reviewed_tickers_when_v2_pilots_enabled(
            watchlist,
            enabled_strategy_ids=(
                _enabled_reviewed_pilots | _enabled_research_observers
            ),
        )
        # Static catalog scope remains the default. A newly qualified ticker
        # joins this user's cycle only after that user explicitly enables the
        # exact published strategy/version in this account's active mode.
        from config.strategy_ticker_recommendations import approved_dynamic_tickers
        for _approved_ticker in approved_dynamic_tickers(settings, _enabled_reviewed_pilots):
            if _approved_ticker not in _with_reviewed and _approved_ticker not in _BL:
                _with_reviewed.append(_approved_ticker)
        if _with_reviewed != watchlist:
            watchlist = _with_reviewed
            _US["scan_watchlist"] = watchlist
            logger.info("reviewed_pilot_added_validated_tickers_to_watchlist")

    # A due research candidate gets one confirmation scan at the end of its
    # 15-minute window.  This is causal: it is a real re-evaluation now, never
    # an order based on stale data from when the window started.
    _opportunity_enabled = bool(
        settings.get("paper_trading", True)
        and settings.get("opportunity_tier_enabled", False)
    )
    if not _opportunity_enabled and _US.get("opportunity_scheduler"):
        _clear_opportunity_window(_US)
    _due_ticker = _opportunity_due_ticker(_US, _now_et()) if _opportunity_enabled else None
    idx = _US.get("scan_idx", 0) % len(watchlist)
    if scan_ticker is not None:
        ticker = scan_ticker
    elif _due_ticker:
        ticker = _due_ticker
        logger.info("opportunity_window_due ticker=%s", ticker)
    else:
        ticker = watchlist[idx]
        _US["scan_idx"] = (idx + 1) % len(watchlist)
    _US["current_ticker"]   = ticker
    logger.debug("Scanning ticker %s (%d/%d)", ticker, idx + 1, len(watchlist))

    # FIX 2026-06-22 (direct request): the per-ticker session-long loss
    # cooldown ("Fix 1") that used to gate here is removed — see the matching

    # ── Fix 2 (new): Same-ticker concurrent position guard ───────────────────
    # MAX_CONCURRENT_POSITIONS=2 is for DIVERSIFICATION — two different stocks,
    # not two legs on the same stock.  Without this guard, both slots can open
    # the same ticker simultaneously (SPY+SPY, NVDA+NVDA), doubling exposure
    _open_tickers = {t.get("ticker", "") for t in _US.get("open_trades", [])}
    if ticker in _open_tickers:
        # Still narrate the open position every bar so the THINKING panel shows
        # live position status for NVDA/SPY even though no new entry is taken.
        try:
            _pos_bars, _pos_err, _ = alpaca.get_session_bars(ticker, "1Min")
            if _pos_bars and not _pos_err:
                _df_pos = bars_to_df(_pos_bars)
                _log_bar_thinking(_df_pos, _df_pos, ticker)
        except Exception as _lbt_ex:
            logger.debug("_log_bar_thinking (in-trade) failed for %s: %s", ticker, _lbt_ex)
        return

    # ── Fix 3 (new): Post-win cooling period ─────────────────────────────────
    # After a profitable close, block the same ticker for WIN_COOLDOWN_MINUTES
    # (10 min).  This prevents the pattern of winning on AAPL then immediately
    # chasing back in 12 seconds later and giving the win back — confirmed as
    _WIN_COOLDOWN_MINUTES = 10
    _win_cooldowns = _US.get("ticker_win_cooldown") or {}
    if ticker in _win_cooldowns:
        _win_expires = _win_cooldowns[ticker]
        _now_check   = _now_et()
        if _now_check < _win_expires:
            _remaining = int((_win_expires - _now_check).total_seconds() / 60) + 1
            log_event("INFO", "bar_eval",
                      f"⏱ [{ticker}] Skipping — post-win cooldown active for ~{_remaining} more "
                      f"minute(s). Preventing immediate re-entry after a winning trade.")
            return
        else:
            # Cooldown expired — remove it so the dict doesn't grow unbounded
            try:
                del _US["ticker_win_cooldown"][ticker]
            except (KeyError, TypeError):
                pass

    # ── Re-entry gate ─────────────────────────────────────────────────────────
    # Bot may re-enter the same ticker after cooldowns expire.  Quality gates:
    #   • loss cooldown (Fix 1): blocks re-entry after any losing trade

    # ── Earnings check — respects earnings_filter_enabled toggle ─────────────
    try:
        _s = get_settings()
        if _s.get("earnings_filter_enabled", True):
            _blackout = int(_s.get("earnings_blackout_days", EARNINGS_BLACKOUT_DAYS))
            earnings  = tradier.get_earnings(ticker)
            if is_near_earnings(earnings, _blackout):
                logger.info("Earnings blackout: %s — skipping", ticker)
                return
    except Exception:
        pass

    # ── Fetch today's 1-min session bars for signal detection ────────────────
    # Switched from 5Min → 1Min so all 8 strategies (BOS/MSS, FVG, VWAP PB,
    # Channel Break, etc.) detect structure shifts at the exact candle they
    try:
        bars_5m, is_error, is_live = alpaca.get_session_bars(ticker, "1Min")
    except Exception as e:
        logger.error("Session bars fetch failed for %s: %s", ticker, e)
        _update_data_gap()
        return

    if is_error or not bars_5m:
        logger.warning("No 1-min bars available for %s — skipping tick", ticker)
        _update_data_gap()
        return

    # ── Successful fetch — reset watchdog ─────────────────────────────────────
    _now_fetch = _now_et()
    _US["last_successful_bar_fetch"] = _now_fetch.isoformat()
    _US["data_gap_minutes"]          = 0

    _US["bars_5m"] = bars_5m   # key name kept for compatibility
    df5 = bars_to_df(bars_5m)

    # ── Augment with historical 5-min bars for cross-day RVOL baseline ───────
    # Alpaca's free IEX tier caps 1Min historical pulls at ~400 bars (today
    # only).  Requesting 7800 1Min bars would either 403 or silently return
    # 5Min history bars (free-tier friendly) prepended for RVOL context only.
    _df_today_1m = df5.copy()   # save today's 1Min bars before augment
    if execution_only:
        from trading.loop.scan_schedule import record_scan_timing
        record_scan_timing(_US, ticker, _df_today_1m, _now_et())
    # Persist every scanner-evaluated ticker's canonical one-minute history.
    # This is reusable prospective research data; it cannot place an order.
    try:
        from database import record_scanner_candles
        record_scanner_candles(
            ticker, _df_today_1m,
            broker_account_id=settings.get("active_broker_account_id") or None,
        )
        _US.setdefault("_batch_archived_tickers", set()).add(ticker)
    except Exception:
        logger.debug("scanner candle archive failed for %s", ticker, exc_info=True)
    try:
        _hist_bars, _hist_err = alpaca.get_bars(ticker, "5Min", limit=1500)  # ~15 days
        if _hist_bars and not _hist_err:
            _df_hist   = bars_to_df(_hist_bars)
            _today_min = df5["time"].min() if not df5.empty else None
            if _today_min is not None:
                _df_hist = _df_hist[_df_hist["time"] < _today_min]
            if not _df_hist.empty:
                # Augmented df used only by RVOL compute inside route_signals.
                # route_signals() receives df_rvol_aug; strategy evaluation is
                df5 = pd.concat([_df_hist, _df_today_1m], ignore_index=True).sort_values("time").reset_index(drop=True)
    except Exception as _hist_ex:
        logger.debug("Historical bar augment skipped (%s): %s", ticker, _hist_ex)

    # ── 1-min df for audit log narration ─────────────────────────────────────
    _df1m = _df_today_1m

    # Per-candle audit log — fires once per newly closed 1-min bar
    _log_bar_thinking(_df1m, df5, ticker)

    # ── Multi-Strategy Router: evaluate enabled strategies, take top signal ──
    # Read the per-strategy enable flags saved by the Risk Settings form.
    # Any flag absent from settings defaults to True (all on by default).
    _strat_cfg = get_settings()
    from config.strategy_catalog import (
        enabled_observation_strategy_ids, enabled_reviewed_strategy_ids,
        reviewed_execution_strategy_ids,
    )
    _enabled = enabled_reviewed_strategy_ids(
        _strat_cfg, ticker=ticker, paper=paper,
    )
    # mtf_cache: per-user, per-ticker cache dict (see trading/state.py's
    # "mtf_1h_cache" key + trading/mtf_live_gate.py) — passing both alpaca and
    # this cache is what turns on the Gap 3 MTF confirmation gate; every other
    # route_signals() caller (backtester, audit tools) omits them and is
    # unaffected. Gate itself still defaults OFF via mtf_confirmation_enabled.
    _candidate_observer = None
    _observation_only_strategies: set[str] = set()
    _observation_resolver = None
    # Evidence collection is account-mode independent.  A live-mode user must
    # not have to switch back to paper merely to keep observing disabled
    # strategy/ticker pairs.  This branch is still read-only: it selects and
    # re-prices hypothetical contracts, but imports no broker order function
    # and never adds a signal to the executable return set.
    if bool(settings.get("shadow_ledger_enabled", True)):
        from shadow_ledger import mark_candidate_observed_only
        # Re-price previously selected scanner contracts at fixed horizons.
        # This is read-only evidence for entered, blocked, and skipped setups;
        # it has no route into order placement or position management.
        try:
            from database.option_quotes import capture_due_candidate_option_quotes
            if not execution_only:
                capture_due_candidate_option_quotes(
                    ticker=ticker, observed_at=_now_et(),
                    quote_lookup=tradier.get_option_quote,
                    broker_account_id=settings.get("active_broker_account_id") or None,
                )
        except Exception:
            logger.debug("candidate option follow-up sweep failed for %s", ticker, exc_info=True)
        if not execution_only:
            _observation_only_strategies = enabled_observation_strategy_ids(
                settings, ticker=ticker,
            )
        if not execution_only and bool(settings.get("shadow_observe_all_strategies", True)):
            _observation_only_strategies |= (
                reviewed_execution_strategy_ids() - _enabled
            )
        if _observation_only_strategies:
            _observation_resolver = mark_candidate_observed_only
        # Price every raw candidate, not only the one which wins same-tick
        # ranking.  This is a read-only preview: it creates no order or trade,
        # but it lets the 30/60/90-minute recorder measure whether the router
        # correctly skipped the other possible setups.  Cache identical chain
        # selections within this tick so observation does not multiply API use.
        from trading.entry.candidate_observation import observe_candidate_contract
        _candidate_preview_cache: dict = {}
        def _candidate_observer(ticker_arg, signal_arg, underlying_arg):
            observe_candidate_contract(
                ticker=ticker_arg, signal=signal_arg, underlying_price=underlying_arg,
                tradier=tradier, balance=balance, risk=_risk, settings=settings,
                selection_cache=_candidate_preview_cache,
            )
    # The router receives approved strategies for potential entry plus a
    # separate observation-only set in either account mode. Observed-only signals cannot make
    # it back out of the router, so they cannot reach contract selection.
    from trading.entry.injected_setups import evaluate_injected_setups
    _injected_signals, _setup_statuses, _live_underlying_quote = evaluate_injected_setups(
        _US, _df_today_1m, ticker, _enabled, _observation_only_strategies, alpaca, settings,
    )

    _signals = route_signals(df5, ticker, enabled_strategies=_enabled,
                              alpaca=alpaca, mtf_cache=_US.setdefault("mtf_1h_cache", {}),
                              candidate_observer=_candidate_observer,
                              observation_only_strategies=_observation_only_strategies,
                              observation_resolver=_observation_resolver,
                              injected_signals=_injected_signals,
                              preserve_reviewed_paid_rules=True)
    from trading.diagnostics.strategy_scan import log_strategy_scan
    log_strategy_scan(_US, ticker, _enabled, _setup_statuses, _signals, _now_et())
    # Main-tier setups remain immediate.  Opportunity setups are paper-only
    # candidates collected and ranked over a causal 15-minute window.
    if _opportunity_enabled:
        _scheduled = _select_opportunity_signal(_US, ticker, _signals, _now_et())
        _candidate = _scheduled.candidate or {}
        if _scheduled.action == "waiting":
            if _scheduled.event in {"started", "replaced"}:
                _US["last_signal"] = "opportunity_waiting"
                _US["last_strategy_id"] = _candidate.get("strategy_id")
                _detail = (
                    f"15-minute ranking window; best={_candidate.get('strategy_id')} "
                    f"{float(_candidate.get('confidence', 0)):.0%}; expires "
                    f"{str(_candidate.get('expires_at', ''))[11:16]} ET"
                )
                log_event("INFO", "bar_eval", f"🟣 [{ticker}] {_detail}")
                _skip_log(
                    ticker, "opportunity_window", strategy=_candidate.get("strategy_id"),
                    confidence=float(_candidate.get("confidence", 0)),
                    direction=_candidate.get("direction"), tier="opportunity", detail=_detail,
                )
            return
        if _scheduled.action == "expired":
            _detail = "15-minute ranking winner no longer confirmed at decision time"
            log_event("INFO", "bar_eval", f"⚪ [{ticker}] Opportunity skipped — {_detail}.")
            _skip_log(
                ticker, "opportunity_confirmation_lost", strategy=_candidate.get("strategy_id"),
                confidence=float(_candidate.get("confidence", 0)),
                direction=_candidate.get("direction"), tier="opportunity", detail=_detail,
            )
            return
        if _scheduled.action == "select":
            if _scheduled.event == "main_preempted" and _candidate:
                _skip_log(
                    _candidate.get("ticker", ticker), "opportunity_preempted", strategy=_candidate.get("strategy_id"),
                    confidence=float(_candidate.get("confidence", 0)),
                    direction=_candidate.get("direction"), tier="opportunity",
                    detail="A main-tier setup arrived before the research window closed.",
                )
            _top: _RouterSignal = _scheduled.signal
        else:
            _top = None
    else:
        _top = _signals[0] if _signals else None

    if _top is None:
        _US["last_signal"] = None
        # Log WHY no signal — the bar_eval entry already covers the ORB gate
        # reasoning; this adds a higher-level "no strategy qualified" note so
        try:
            _last_bar_t = str(df5["time"].iloc[-1]) if not df5.empty else "?"
            log_event("INFO", "bar_eval",
                      f"🟡 [{ticker}] {_last_bar_t[11:16]} — No trade setup found on this candle. "
                      f"Conditions not yet aligned — continuing to watch.")
        except Exception:
            pass
        _skip_log(ticker, "no_signal")   # visible in dashboard eval log
        return

    direction   = _top.direction      # "bullish" | "bearish"
    entry_rvol  = _top.rvol           # Entry_Volume_Multiplier for audit log
    strategy_id = _top.strategy_id
    _signal_tier = getattr(_top, "tier", "main")
    _reviewed_paid_profile = uses_reviewed_paid_execution_profile(strategy_id)
    # The session cutoff must include the strategy's complete reviewed hold.
    # Otherwise a late signal can create an overnight position before the
    # fixed 30/90-minute exit becomes eligible.
    if uses_v2_orb_execution_profile(strategy_id):
        # Keep this distinct from the stdlib ``time`` module imported near the
        # top of this function.  Reusing ``_time`` here used to replace the
        # module for the entire function scope, causing every qualified V2
        # entry to crash after contract selection at ``_time.strftime``.
        from datetime import time as _datetime_time
        from trading.v2_orb_paper_exit import reviewed_entry_fits_session
        _entry_fits, _entry_fit_reason = reviewed_entry_fits_session(
            _now_et(), strategy_id, cutoff=_datetime_time(*SESSION_HARD_CUTOFF_HM),
        )
        if not _entry_fits:
            log_event("INFO", "trading_logic", f"🟡 [{ticker}] {strategy_id} skipped — {_entry_fit_reason}.")
            _skip_log(ticker, "reviewed_hold_crosses_session_cutoff")
            return
    _US["last_signal"]     = direction
    _US["last_strategy_id"]= strategy_id
    from config.strategy_catalog import reviewed_exit_summary
    # The Scanner needs a reproducible *recipe* even if a later account or
    # liquidity gate stops this setup before a particular option can be
    # selected.  This describes the exact selector's rules, not a fabricated
    # historical strike, expiry, or fill.  The selected contract is appended
    # below only after the broker actually returned one at decision time.
    _recipe_cap_pct = settings.get("max_position_dollars_pct")
    try:
        _recipe_max_spend = (
            float(balance) * (float(_recipe_cap_pct) / 100.0)
            if _recipe_cap_pct else float(settings.get("max_position_dollars", 750.0))
        )
    except (TypeError, ValueError):
        _recipe_max_spend = 0.0
    _reviewed_recipe = uses_v2_orb_execution_profile(strategy_id)
    _contract_recipe = {
        "option_type": "CALL" if direction == "bullish" else "PUT",
        "strike_rule": "closest out-of-the-money strike to the underlying at selection",
        "premium_rule": (
            "$0.80–$10.00 ask" if _reviewed_recipe
            else f"${MIN_CONTRACT_COST:.2f}–${MAX_CONTRACT_COST:.2f} ask"
        ),
        "expiration_rule": "7–21 calendar days to expiration" if _reviewed_recipe else "first broker-listed expiration with a qualifying contract",
        "spread_rule": "bid/ask spread no wider than 8% of mid" if _reviewed_recipe else f"bid/ask spread no wider than {float(settings.get('spread_gate_pct', 8) or 8):.0f}% of mid",
        "liquidity_rule": "broker-returned liquid chain" if _reviewed_recipe else f"open interest of at least {MIN_OPEN_INTEREST}",
        "maximum_cost": round(_recipe_max_spend, 2),
        "selection_model": "reviewed paid-quote profile" if _reviewed_recipe else "standard liquid first-OTM profile",
    }
    # Durable, read-only explanation for Scanner Opportunities.  It begins
    # with the signal facts and is enriched below only when contract selection
    # succeeds.  This snapshot is never read by placement or exit logic.
    _US["scanner_opportunity_context"] = {
        "ticker": ticker.upper(),
        "strategy_id": strategy_id,
        "context": {
            "trigger_bar": str(_top.trigger_bar),
            "strategy_meta": _top.meta,
            "entry_plan": {
                "trigger": "qualifying setup reached the entry router",
                "underlying_price": None,
            },
            "contract_recipe": _contract_recipe,
            # This is recorded before any gate can stop the setup, so the
            # learner can see the intended exit rule even when no contract
            # was ultimately affordable or liquid enough to select.
            "exit_plan": {
                "strategy_id": strategy_id,
                "summary": reviewed_exit_summary(strategy_id),
            },
        },
    }

    # SPY Trend Continuation and Afternoon FVG compete for the same SPY
    # position slot. Chronological paid-quote portfolio research selected
    # preserving that slot for FVG from 13:45 through 15:00 ET. This is not a
    # daily trade cap and does not affect any other ticker or strategy.
    from trading.portfolio_policy import reviewed_portfolio_entry_policy
    _portfolio_decision = reviewed_portfolio_entry_policy(
        ticker=ticker,
        strategy_id=strategy_id,
        now_et=_now_et(),
        settings=settings,
    )
    if not _portfolio_decision.allowed:
        _opportunity_context = _US["scanner_opportunity_context"]["context"]
        if isinstance(_opportunity_context, dict):
            _opportunity_context["portfolio_policy"] = {
                "status": "reserved",
                "reason_code": _portfolio_decision.reason_code,
                "reason_detail": _portfolio_decision.reason_detail,
            }
        log_event(
            "INFO",
            "trading_logic",
            f"🟡 [{ticker}] {strategy_id} skipped — "
            f"{_portfolio_decision.reason_detail}",
        )
        _log_journal(
            ticker,
            strategy_id,
            direction,
            _top.confidence,
            outcome="blocked",
            reason_code=_portfolio_decision.reason_code,
            reason_detail=_portfolio_decision.reason_detail,
            context=_opportunity_context,
            tier=_signal_tier,
        )
        return

    # ── Manual-trade contract preview (display only; never an order) ─────────
    # Scanner Opportunities is also a learning/manual-review surface.  A
    # router gate used to stop a signal *before* contract selection, leaving a
    # learner with no strike, expiry, quote, or estimated size to inspect.
    # Take one clearly-labelled display snapshot as soon as the strategy has
    # qualified.  The normal entry path intentionally re-queries immediately
    # before an order, so this preview can never become a stale execution
    # instruction or alter the actual order decision.
    quote = _live_underlying_quote or alpaca.get_latest_quote(ticker)
    if not quote:
        return
    current_price = (quote.get("ap", 0) + quote.get("bp", 0)) / 2
    if current_price <= 0:
        return
    _opportunity_context = _US.get("scanner_opportunity_context", {}).get("context")
    if isinstance(_opportunity_context, dict):
        _entry_plan = _opportunity_context.setdefault("entry_plan", {})
        if isinstance(_entry_plan, dict):
            _entry_plan["underlying_price"] = round(float(current_price), 4)

    _cap_pct = settings.get("max_position_dollars_pct")
    if _cap_pct:
        _preview_max_spend = balance * (float(_cap_pct) / 100.0)
    else:
        _preview_max_spend = float(settings.get("max_position_dollars", 750.0))
    _v2_paid_parity = uses_v2_orb_execution_profile(strategy_id)
    try:
        if _v2_paid_parity:
            _preview_contract, _preview_info = select_reviewed_v2_contract(
                tradier, ticker, direction, current_price, _preview_max_spend,
                for_display=True,
            )
        else:
            _preview_contract, _preview_info = select_contract(
                tradier, ticker, direction, current_price, _preview_max_spend,
                for_display=True,
            )
    except Exception:
        # The preview is explanatory telemetry only.  A temporary chain
        # problem must not make the real entry flow less reliable.
        _preview_contract, _preview_info = None, {"reason": "preview_unavailable"}
        logger.debug("manual contract preview failed for %s", ticker, exc_info=True)
    if isinstance(_opportunity_context, dict):
        _preview = {
            "status": "selected" if _preview_contract else "not_selected",
            "observed_at": _now_et().isoformat(),
            "underlying_price": round(float(current_price), 4),
            "reason": str(_preview_info.get("reason") or "not_selected"),
            "cheapest_cost": _preview_info.get("cheapest_cost"),
            "cheapest_symbol": _preview_info.get("cheapest_symbol"),
            "illiquid_cost": _preview_info.get("illiquid_cost"),
            "illiquid_symbol": _preview_info.get("illiquid_symbol"),
            "liquidity_detail": _preview_info.get("illiquid_fail"),
            "eligible_contract_count": _preview_info.get("eligible_contract_count"),
            "shadow_contract_leaderboard": _preview_info.get("shadow_contract_leaderboard", []),
        }
        if _preview_contract:
            _preview_bid = float(_preview_contract.get("bid") or 0.0)
            _preview_ask = float(_preview_contract.get("ask") or 0.0)
            _preview_midpoint = (
                round((_preview_bid + _preview_ask) / 2.0, 4)
                if _preview_bid > 0 else _preview_ask
            )
            _preview_working, _preview_step = entry_limit_prices(
                ask=_preview_ask,
                midpoint=_preview_midpoint,
                v2_paper_pilot=_v2_paid_parity,
            )
            _preview_max_entry = _risk.slippage_adjusted_entry(_preview_ask)
            # Size against the hard ceiling even though the order may begin at
            # a better price. A later reprice must not exceed approved risk.
            _preview_contracts = _risk.calculate_contracts(_preview_max_entry, balance)
            if _signal_tier == "opportunity" and _preview_contracts > 1:
                _preview_contracts = max(1, _preview_contracts // 2)
            # Mirror the same notional ceiling later used by the order path.
            _preview_growth = bool(settings.get("growth_mode", False)) and balance < float(
                settings.get("growth_risk_boundary_boot", 5000.0)
            )
            _preview_risk_pct = _risk.effective_risk_pct(balance)
            _preview_notional_pct = .45 if _preview_growth else (.30 if _preview_risk_pct > .01 else .20)
            _preview_notional_cap = balance * _preview_notional_pct
            _preview_contracts = min(
                _preview_contracts,
                max(1, int(_preview_notional_cap // max(_preview_ask * 100, 0.01))),
            )
            _preview.update({
                "symbol": _preview_contract.get("symbol"),
                "strike": _preview_contract.get("strike"),
                "expiry": _preview_contract.get("expiry"),
                "bid": _preview_contract.get("bid"),
                "ask": _preview_contract.get("ask"),
                "spread": _preview_contract.get("spread"),
                "volume": _preview_contract.get("volume"),
                "open_interest": _preview_contract.get("open_interest"),
                "selection_model": _preview_contract.get("selection_model"),
                "planned_entry_price": round(_preview_working, 4),
                "working_limit": round(_preview_working, 4),
                "step_limit": round(_preview_step, 4) if _preview_step is not None else None,
                "maximum_entry_price": round(_preview_max_entry, 4),
                "planned_contracts": int(_preview_contracts),
                "estimated_position_cost": round(_preview_max_entry * _preview_contracts * 100, 2),
            })
        _opportunity_context["contract_preview"] = _preview
        # Save the plan now—not only when a later gate produces a journal row.
        # A signal can legitimately stop at an early safety gate below.
        try:
            from shadow_ledger import snapshot_candidate_plan
            snapshot_candidate_plan(_opportunity_context)
            from database.option_quotes import record_candidate_option_quote
            _candidate_id = (_top.meta or {}).get("shadow_candidate_id") if isinstance(_top.meta, dict) else None
            if _candidate_id and _preview_contract:
                record_candidate_option_quote(
                    candidate_id=_candidate_id,
                    contract_symbol=str(_preview_contract.get("symbol") or ""),
                    observation_kind="entry", observed_at=_now_et(),
                    quote=_preview_contract, source="tradier_contract_preview",
                )
        except Exception:
            logger.debug("manual plan snapshot failed for %s", ticker, exc_info=True)

    # ── Minimum confidence gate — REMOVED 2026-07-18 (was dead code) ─────────
    # This used to re-check _top.confidence against a local 0.55 floor. It
    # could never fire: strategy_router.route_signals()'s last gate
    # (apply_confidence_floor, in router_gates.py) already drops every signal
    # below 0.74 before returning, so nothing reaching this point could ever
    # be < 0.55. It read as an active safety check in the logs ("skipped —
    # confidence below minimum") but was unreachable. The real confidence
    # floor lives in strategy_router.py's `_MIN_CONFIDENCE = 0.74` — change
    # it there, not here, if you want to adjust how selective the router is.

    # ── Post-loss price displacement gate ────────────────────────────────────
    # ── 0.3% price displacement gate (all strategies) ────────────────────────
    # After any loss, price must move at least 0.3% from the exit level before
    # the same ticker can be re-entered.  Ensures the failed setup has resolved.
    _loss_ctx = (_US.get("ticker_loss_context") or {}).get(ticker)
    if _loss_ctx and not _reviewed_paid_profile:
        _last_exit_price = _loss_ctx.get("exit_price", 0)
        try:
            _current_price   = float(df5["close"].iloc[-1])
            _price_moved_pct = abs(_current_price - _last_exit_price) / _last_exit_price if _last_exit_price else 1.0
        except Exception:
            _price_moved_pct = 1.0
        if _price_moved_pct < 0.003:
            log_event("INFO", "bar_eval",
                      f"⚪ [{ticker}] Post-loss skip — price {_current_price:.2f} is within "
                      f"{_price_moved_pct:.2%} of last loss exit {_last_exit_price:.2f}. "
                      f"Waiting for price to move to a new level.")
            return


    # ── Flip-direction enforcement ────────────────────────────────────────────
    # When flip_eligible, we prefer the OPPOSITE direction of the stopped trade
    # but we do NOT hard-block a valid signal — market structure always wins.
    if _US.get("flip_eligible"):
        required_flip = _US.get("flip_direction")
        if direction != required_flip:
            logger.info(
                "Flip mismatch — signal=%s required=%s; proceeding with signal "
                "(market structure overrides stale flip token)",
                direction, required_flip,
            )
            log_event("INFO", "bar_eval",
                      f"[{ticker}] Flip preference was {required_flip} but "
                      f"signal is {direction} — market structure wins, entering.")
            # Clear the stale flip token so it doesn't keep logging on every tick
            _US["flip_eligible"]  = False
            _US["flip_direction"] = None
            _US["flip_ticker"]    = None
        else:
            logger.info(
                "flip_signal_confirmed",
                extra={
                    "event":          "flip_signal_confirmed",
                    "ticker":         ticker,
                    "flip_direction": direction,
                    "prev_direction": _US.get("last_direction"),
                },
            )

    # Mandatory signal log — emitted for every qualifying signal before
    # any sizing or R:R check so we have a full audit trail of every trigger.
    logger.info(
        "trade_signal_detected",
        extra={
            "event":       "trade_signal_detected",
            "ticker":      ticker,
            "direction":   direction,
            "Strategy_ID": strategy_id,
            "confidence":  round(_top.confidence, 3),
            "is_flip":     bool(_US.get("flip_eligible")),
            "status":      "PENDING_RR_GATE",
        },
    )

    # ── SPY VWAP direction gate ───────────────────────────────────────────────
    # Before entering a CALL, confirm SPY is trading ABOVE its intraday VWAP.
    # If SPY is below VWAP the broad market is in a bearish posture; bullish
    # ── SPY macro VWAP check — flip direction rather than block ──────────────
    if not _reviewed_paid_profile and ticker.upper() in ("SPY", "QQQ"):
        try:
            from signals import compute_vwap_bands as _cvwap_self
            _self_vwap_data = _cvwap_self(_df_today_1m)
            _self_vwap  = float(_self_vwap_data["vwap"].iloc[-1]) if "vwap" in _self_vwap_data.columns else 0.0
            _self_close = float(_df_today_1m["close"].iloc[-1]) if not _df_today_1m.empty else 0.0
            # 2026-07-15 audit: was a direction FLIP (CALL→PUT) that kept the
            # original strategy's entry timing — e.g. a VWAP-pullback long flipped
            if _self_vwap > 0:
                if direction == "bullish" and _self_close < _self_vwap:
                    log_event("INFO", "bar_eval",
                              f"⚪ [{ticker}] Skipping CALL — {ticker} (${_self_close:.2f}) "
                              f"is BELOW its own VWAP (${_self_vwap:.2f}). "
                              f"Signal conflicts with macro posture.")
                    _skip_log(ticker, "macro_vwap_veto", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                             detail=f"{ticker} ${_self_close:.2f} below own VWAP ${_self_vwap:.2f}")
                    return
                elif direction == "bearish" and _self_close > _self_vwap:
                    log_event("INFO", "bar_eval",
                              f"⚪ [{ticker}] Skipping PUT — {ticker} (${_self_close:.2f}) "
                              f"is ABOVE its own VWAP (${_self_vwap:.2f}). "
                              f"Signal conflicts with macro posture.")
                    _skip_log(ticker, "macro_vwap_veto", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                             detail=f"{ticker} ${_self_close:.2f} above own VWAP ${_self_vwap:.2f}")
                    return
                else:
                    logger.debug(
                        "self_vwap_aligned ticker=%s direction=%s close=%.2f vwap=%.2f",
                        ticker, direction, _self_close, _self_vwap,
                    )
        except Exception as _self_vwap_ex:
            logger.debug("SPY/QQQ own VWAP gate failed (%s): %s", ticker, _self_vwap_ex)

    # For non-SPY/QQQ tickers: use SPY as the macro VWAP proxy.
    # Exception: skip the flip when ticker IS SPY — no circular self-check.
    if not _reviewed_paid_profile and ticker.upper() not in ("SPY", "QQQ"):
        _spy_df    = None
        _spy_vwap  = 0.0
        _spy_close = 0.0

        # ── Attempt 1: Alpaca (IEX) — works for equities, not ETFs ──────────
        try:
            _spy_bars, _spy_err, _ = alpaca.get_session_bars("SPY", "5Min")
            if _spy_bars and not _spy_err and len(_spy_bars) >= 2:
                from signals import bars_to_df as _b2df, compute_vwap_bands as _cvwap
                _spy_df    = _b2df(_spy_bars)
                _vwap_data = _cvwap(_spy_df)
                _spy_vwap  = float(_vwap_data["vwap"].iloc[-1]) if "vwap" in _vwap_data.columns else 0.0
                _spy_close = float(_spy_df["close"].iloc[-1]) if not _spy_df.empty else 0.0
        except Exception as _vwap_ex:
            logger.debug("SPY Alpaca fetch skipped (%s): %s", ticker, _vwap_ex)

        # ── Attempt 2: yfinance fallback — IEX doesn't carry SPY (NYSE Arca ETF) ──
        # This is the common path in production. The SPY VWAP gate was silently
        # broken whenever Alpaca returned empty for SPY (which is always on IEX).
        if _spy_vwap == 0.0:
            try:
                import yfinance as _yf
                import pandas as _pd_yf
                _spy_yf = _yf.download("SPY", period="1d", interval="5m",
                                       progress=False, auto_adjust=True)
                if not _spy_yf.empty:
                    # Flatten MultiIndex columns (yfinance ≥0.2)
                    if isinstance(_spy_yf.columns, _pd_yf.MultiIndex):
                        _spy_yf.columns = _spy_yf.columns.get_level_values(0)
                    _spy_yf = _spy_yf.rename(columns={
                        "Open": "open", "High": "high",
                        "Low": "low", "Close": "close", "Volume": "volume",
                    })
                    # VWAP via cumulative (price × volume) / cumulative volume
                    _spy_yf["_tp"]   = (_spy_yf["high"] + _spy_yf["low"] + _spy_yf["close"]) / 3
                    _spy_yf["_tpv"]  = _spy_yf["_tp"] * _spy_yf["volume"]
                    _spy_vwap        = float(_spy_yf["_tpv"].sum() / _spy_yf["volume"].sum())
                    _spy_close       = float(_spy_yf["close"].iloc[-1])
                    logger.debug("SPY VWAP gate via yfinance: close=%.2f vwap=%.2f", _spy_close, _spy_vwap)
            except Exception as _yf_ex:
                logger.debug("SPY yfinance fallback failed (%s): %s", ticker, _yf_ex)

        # ── SPY VWAP macro VETO (2026-07-15 audit: was a direction flip) ──────
        # Flipping direction while keeping the strategy's entry timing inverted
        # the strategy's premise. Now: macro disagreement = no trade.
        if _spy_vwap > 0:
            if direction == "bullish" and _spy_close < _spy_vwap:
                log_event("INFO", "bar_eval",
                          f"⚪ [{ticker}] Skipping CALL — SPY (${_spy_close:.2f}) "
                          f"is BELOW VWAP (${_spy_vwap:.2f}). "
                          f"Signal conflicts with macro posture.")
                _skip_log(ticker, "macro_vwap_veto", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                         detail=f"SPY ${_spy_close:.2f} below VWAP ${_spy_vwap:.2f}")
                return
            elif direction == "bearish" and _spy_close > _spy_vwap:
                log_event("INFO", "bar_eval",
                          f"⚪ [{ticker}] Skipping PUT — SPY (${_spy_close:.2f}) "
                          f"is ABOVE VWAP (${_spy_vwap:.2f}). "
                          f"Signal conflicts with macro posture.")
                _skip_log(ticker, "macro_vwap_veto", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                         detail=f"SPY ${_spy_close:.2f} above VWAP ${_spy_vwap:.2f}")
                return
            else:
                logger.debug(
                    "spy_vwap_gate_aligned ticker=%s direction=%s "
                    "spy_close=%.2f spy_vwap=%.2f",
                    ticker, direction, _spy_close, _spy_vwap,
                )

    # ── Select contract ───────────────────────────────────────────────────────
    opt_type = "call" if direction == "bullish" else "put"
    # Budget cap now SCALES with the account: max_spend = balance × max_position_dollars_pct.
    # max_position_dollars_pct (15) was previously a dead setting — $750 was a
    max_spend = _preview_max_spend
    # V2's paid TSLA study used a distinct, predeclared contract rule.  Keep
    # Lock the V2 strategy to its reviewed contract definition in *both* paper
    # and a future explicitly-approved live mode.  Today V2 remains disabled
    # and paper-only through its settings gate; this removes a hidden cleanup
    # task rather than enabling an order path.
    if _v2_paid_parity:
        contract, _sel_info = select_reviewed_v2_contract(
            tradier, ticker, direction, current_price, max_spend,
        )
    else:
        contract, _sel_info = select_contract(tradier, ticker, direction, current_price, max_spend)
    if not contract:
        if isinstance(_opportunity_context, dict):
            _opportunity_context["contract_selection"] = {
                "status": "not_selected",
                "reason": str(_sel_info.get("reason") or "filtered"),
                "cheapest_cost": _sel_info.get("cheapest_cost"),
                "cheapest_symbol": _sel_info.get("cheapest_symbol"),
                "illiquid_cost": _sel_info.get("illiquid_cost"),
                "illiquid_symbol": _sel_info.get("illiquid_symbol"),
                "liquidity_detail": _sel_info.get("illiquid_fail"),
            }
        _reason = _sel_info.get("reason")
        if _reason == "over_budget":
            # We saw real chain data — report the actual premium needed vs. budget.
            _needed = _sel_info.get("cheapest_cost")
            log_event("INFO", "bar_eval",
                      f"🔴 [{ticker}] Cheapest available {opt_type.upper()} contract "
                      f"({_sel_info.get('cheapest_symbol', '?')}) costs ~${_needed:.0f}, "
                      f"but your budget is set to ${max_spend:.0f}. "
                      f"Skipping this setup — will check again next candle.")
            _skip_log(ticker, "budget", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                     detail=f"cheapest ~${_needed:.0f} vs ${max_spend:.0f} budget")
        elif _reason == "illiquid":
            # 2026-07-24: a contract existed WITHIN budget but failed the
            # spread/OI liquidity filters — the real blocker here is
            # liquidity, not account size, even though a budget-limited
            # search is what surfaced it. Distinct from "over_budget" so
            # the signal journal doesn't misreport this as a money problem.
            _cheap_afford = _sel_info.get("illiquid_cost")
            _fail_detail  = _sel_info.get("illiquid_fail", "liquidity filter")
            log_event("INFO", "bar_eval",
                      f"🔴 [{ticker}] {_sel_info.get('illiquid_symbol', '?')} costs "
                      f"~${_cheap_afford:.0f} (within your ${max_spend:.0f} budget) but "
                      f"failed the liquidity filter ({_fail_detail}). "
                      f"Skipping this setup — will check again next candle.")
            _skip_log(ticker, "illiquid_contract", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                     detail=f"${_cheap_afford:.0f} within budget but {_fail_detail}")
        elif _reason in ("api_error", "no_expirations", "no_chain_data"):
            # Tradier didn't return usable options data — NOT a budget issue.
            log_event("INFO", "bar_eval",
                      f"🔴 [{ticker}] Couldn't load {opt_type.upper()} option prices from "
                      f"Tradier (no data returned). Skipping this setup — will check again "
                      f"next candle.")
            _skip_log(ticker, "no_option_data", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                     detail="Tradier returned no usable chain data")
        else:
            # "filtered" — chain data existed but spread/open-interest filters
            # rejected every candidate (not a budget issue).
            log_event("INFO", "bar_eval",
                      f"🔴 [{ticker}] No {opt_type.upper()} contracts met liquidity/spread "
                      f"requirements. Skipping this setup — will check again next candle.")
            _skip_log(ticker, "no_liquid_contracts", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                     detail="no contract met spread/open-interest filters")
        return

    # Refresh the exact selected OCC contract immediately before sizing.  The
    # chain snapshot can be several seconds old by the time all strategy gates
    # clear; using one fresh Tradier quote here keeps contract selection,
    # affordability, quantity, the learner-facing plan, and the submitted
    # Alpaca limit on one price reference.
    _quote_started = time.monotonic()
    try:
        _fresh_quote = tradier.get_option_quote(str(contract.get("symbol") or ""))
    except Exception:
        _fresh_quote = None
        logger.warning("Fresh Tradier entry quote failed for %s", contract.get("symbol"), exc_info=True)
    _quote_latency_ms = round((time.monotonic() - _quote_started) * 1000, 1)
    _fresh_bid = float((_fresh_quote or {}).get("bid") or 0)
    _fresh_ask = float((_fresh_quote or {}).get("ask") or 0)
    _fresh_age = (_fresh_quote or {}).get("quote_age_seconds")
    if _fresh_bid <= 0 or _fresh_ask < _fresh_bid:
        log_event(
            "INFO", "bar_eval",
            f"🟡 [{ticker}] Fresh Tradier quote unavailable for "
            f"{contract.get('symbol', 'selected contract')} — skipping instead "
            f"of sizing or ordering from a stale chain price.",
        )
        _skip_log(
            ticker, "fresh_entry_quote_unavailable", strategy=strategy_id,
            confidence=_top.confidence, direction=direction, tier=_signal_tier,
            detail=f"Tradier exact-contract quote missing after {_quote_latency_ms:.1f}ms",
        )
        return
    if not _entry_quote_is_fresh(_fresh_quote):
        _age_detail = (
            f"{float(_fresh_age):.1f}s old" if _fresh_age is not None
            else "missing a broker timestamp"
        )
        log_event(
            "WARNING", "bar_eval",
            f"🟡 [{ticker}] Tradier quote for {contract.get('symbol')} is "
            f"{_age_detail}. Entry blocked because delayed prices cannot be used "
            "for an executable order.",
        )
        _skip_log(
            ticker, "stale_entry_quote", strategy=strategy_id,
            confidence=_top.confidence, direction=direction, tier=_signal_tier,
            detail=f"Tradier exact-contract quote was {_age_detail}",
        )
        return
    contract.update({
        "bid": _fresh_bid,
        "ask": _fresh_ask,
        "mid": (_fresh_bid + _fresh_ask) / 2,
        "spread": _fresh_ask - _fresh_bid,
        "quote_source": "tradier_production",
        "quote_latency_ms": _quote_latency_ms,
        "quote_age_seconds": float(_fresh_age),
        "quote_received_at": _fresh_quote.get("quote_received_at") or _now_et().isoformat(),
        "quote_bid_time_ms": _fresh_quote.get("bid_date"),
        "quote_ask_time_ms": _fresh_quote.get("ask_date"),
    })
    ask_price = _fresh_ask

    # ── Slippage-adjusted entry price ─────────────────────────────────────────
    # All sizing and R:R calculations use the worst-case fill (ask + 5% slippage)
    # so we never enter a trade whose numbers only work at the quoted price.
    eff_entry = _risk.slippage_adjusted_entry(ask_price)
    if isinstance(_opportunity_context, dict):
        _opportunity_context["contract"] = {
            "symbol": contract.get("symbol"), "strike": contract.get("strike"),
            "expiry": contract.get("expiry"), "bid": contract.get("bid"),
            "ask": contract.get("ask"), "spread": contract.get("spread"),
            "volume": contract.get("volume"),
            "open_interest": contract.get("open_interest"),
            "selection_model": contract.get("selection_model"),
        }
        _entry_plan = _opportunity_context.setdefault("entry_plan", {})
        if isinstance(_entry_plan, dict):
            _entry_plan["estimated_entry_price"] = round(float(eff_entry), 4)
            _entry_plan["trigger"] = "enter only after every router, liquidity, and risk gate clears"
        _opportunity_context["contract_selection"] = {
            "status": "selected",
            "reason": str(_sel_info.get("reason") or "selected"),
            "selected_dte": _sel_info.get("selected_dte"),
            "selected_spread_pct": _sel_info.get("selected_spread_pct"),
        }

    # ── Record what the bot is currently looking at, for the dashboard ───────
    # Surfaces the live contract premium + affordability ceiling proactively
    # (without the user having to ask) by writing them into _US and
    # patching bot_state.json immediately, instead of waiting for next tick.
    _US["last_eval_ticker"]           = ticker
    _US["last_eval_opt_type"]         = opt_type
    _US["last_eval_premium"]          = ask_price
    _US["last_eval_eff_entry"]        = eff_entry
    _US["last_eval_time"]             = _time.strftime("%H:%M:%S")
    _US["last_eval_expiry"]           = contract.get("expiry")
    _US["last_eval_strike"]           = contract.get("strike")
    _US["last_eval_contract_symbol"]  = contract.get("symbol")
    try:
        atomic_update_json(_state_path, lambda state: {
            **state,
            "last_eval_ticker": ticker,
            "last_eval_opt_type": opt_type,
            "last_eval_premium": ask_price,
            "last_eval_eff_entry": eff_entry,
            "last_eval_time": _US["last_eval_time"],
            "last_eval_expiry": _US["last_eval_expiry"],
            "last_eval_strike": _US["last_eval_strike"],
            "last_eval_contract_symbol": _US["last_eval_contract_symbol"],
            "risk_budget_usd": round(balance * _risk.effective_risk_pct(balance), 2),
            "max_affordable_premium": _risk.max_affordable_premium(balance),
        })
    except Exception:
        pass   # non-critical — next full tick write will catch up regardless

    # ── ORB 1% risk sizing (uses slippage-adjusted price) ─────────────────────
    n_contracts = _risk.calculate_contracts(eff_entry, balance)

    # Opportunity signals are a paper-only research cohort. They retain every
    # existing liquidity/R:R/risk check but cannot use more than half of the
    # main-tier size (one contract is the indivisible minimum).
    if _signal_tier == "opportunity" and n_contracts > 1:
        n_contracts = max(1, n_contracts // 2)

    if n_contracts < 1:
        logger.warning(
            "ORB sizing returned 0 contracts",
            extra={"event": "sizing_zero", "ask": ask_price, "eff_entry": eff_entry, "balance": balance},
        )
        # Spell out the RISK vs PRICE distinction so this isn't confused with the
        # max_position_dollars / "over_budget" cost cap above. SIZING_ZERO fires
        _risk_pct          = _risk.effective_risk_pct(balance)
        _risk_per_contract = eff_entry * _risk.ORB_STOP_PCT * 100
        _risk_budget       = balance * _risk_pct
        log_event("INFO", "bar_eval",
                  f"🔴 [{ticker}] Contract premium ${ask_price:.2f} (${eff_entry:.2f} w/ 5% "
                  f"slippage) — if the 30% stop hits, 1 contract would lose "
                  f"${_risk_per_contract:.2f}, but your risk budget is only "
                  f"${_risk_budget:.2f} ({_risk_pct*100:.0f}% of ${balance:.2f}). "
                  f"Need a bigger risk budget (raise risk_per_trade or grow the "
                  f"account) or a cheaper-premium contract.")
        _skip_log(ticker, "zero_contracts", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                 detail=f"1 contract risks ${_risk_per_contract:.0f}, budget is ${_risk_budget:.0f}")
        return

    # ── Total-position-cost cap (tier-aware notional cap) ─────────────────────
    # calculate_contracts() already has a built-in notional cap (45%/30%/20% of
    # balance). The old secondary clamp used max_spend (15% of balance = $267 on
    _in_bs_clamp = bool(settings.get("growth_mode", False)) and \
                   balance < float(settings.get("growth_risk_boundary_boot", 5000.0))
    _eff_rp_clamp = _risk.effective_risk_pct(balance)
    if _in_bs_clamp:
        _notional_pct = 0.45          # bootstrap: matches calculate_contracts()
    elif _eff_rp_clamp > 0.01:        # growth / mid tier (> 1%)
        _notional_pct = 0.30
    else:
        _notional_pct = 0.20          # conservative (1%)
    _notional_cap   = balance * _notional_pct
    _max_affordable = max(1, int(_notional_cap // (ask_price * 100)))
    if n_contracts > _max_affordable:
        logger.info(
            "Sizing clamp for %s: risk model wanted %d contracts ($%.0f total), "
            "notional cap (%.0f%% = $%.0f) allows %d",
            ticker, n_contracts, n_contracts * ask_price * 100,
            _notional_pct * 100, _notional_cap, _max_affordable,
        )
        n_contracts = _max_affordable

    # A newly qualified dynamic strategy/ticker match still requires this
    # user's explicit consent. Once enabled, it uses the same risk-based sizing
    # as every other reviewed strategy—there is no separate pilot clamp.
    try:
        from config.strategy_ticker_recommendations import is_live_enabled_pair
        _user_approved_match = is_live_enabled_pair(strategy_id, ticker, settings)
    except Exception:
        logger.exception("Could not evaluate live approval for %s/%s", strategy_id, ticker)
        _user_approved_match = False

    if isinstance(_opportunity_context, dict):
        _opportunity_context["planned_quantity"] = int(n_contracts)
        _opportunity_context["exit_plan"] = {
            "strategy_id": strategy_id,
            "summary": reviewed_exit_summary(strategy_id),
        }

    # ── Persist contract count AFTER clamp so dashboard shows actual count ─────
    # (Previously written before the clamp, so the eval log showed 2c while the
    # bot actually traded 1c — now both reflect the same post-clamp number.)
    _US["last_eval_contracts"] = n_contracts
    try:
        with open(_state_path) as _f:
            _bs_c = _json.load(_f)
        _bs_c["last_eval_contracts"] = n_contracts

        # ── Append to running eval_log (last 10 entries) ─────────────────────
        # Each entry represents one contract the bot evaluated — kept as a
        # scrollable list in the dashboard so every option considered is visible.
        _s1_target = round(eff_entry * 1.5, 2)
        _profit    = round(eff_entry * 0.5 * n_contracts * 100, 2)
        _new_entry = {
            "ts":        _US.get("last_eval_time", ""),
            "ticker":    ticker,
            "opt_type":  opt_type,
            "strike":    contract.get("strike"),
            "expiry":    contract.get("expiry"),
            "contracts": n_contracts,
            "eff_entry": round(eff_entry, 2),
            "s1_target": _s1_target,
            "profit":    _profit,
            "strategy":  strategy_id,
            "user_approved_match": _user_approved_match,
            # "signal" = manual mode alert (bot won't execute), "auto" = bot will execute
            "mode":      "signal" if settings.get("signal_only_mode", False) else "auto",
        }
        _log = list(_US.get("eval_log", []))  # read from memory, not file
        _log.insert(0, _new_entry)                    # newest first
        # FIX 2026-07-28: cap was 10 across EVERY evaluation on EVERY ticker —
        # with dozens of tickers evaluated multiple times per tick, a single
        # ticker's entry (e.g. a real NFLX entry) could fall off within
        # moments even though it was never removed on purpose. 50 gives real
        # entries room to survive a few minutes of other tickers' activity.
        _US["eval_log"] = _log[:50]            # update in-memory copy first
        atomic_update_json(
            _state_path, lambda state: {**state, "eval_log": _US["eval_log"]},
        )
    except Exception:
        pass  # non-critical — next full tick write will catch up

    # ── Spread gate: skip if bid-ask spread > 10% of mid price ───────────────
    # Wide spreads mean we pay an immediate 5–10% toll just getting in and out.
    # On a small account that single spread can wipe a whole risk-budget unit.
    _c_bid = float(contract.get("bid", 0) or 0)
    _c_ask = float(contract.get("ask", 0) or ask_price)
    _c_mid = (_c_bid + _c_ask) / 2 if _c_bid > 0 else _c_ask
    if _c_mid > 0:
        _spread_pct = (_c_ask - _c_bid) / _c_mid
        # Reviewed quote studies own their entry liquidity definition (8% of
        # mid) so a later display/settings preference cannot silently turn the
        # historical strategy into a different one. The contract selector has
        # already applied this same threshold before reaching this point.
        _spread_max = 0.08 if _reviewed_paid_profile else float(settings.get("spread_gate_pct", 8)) / 100.0
        if _spread_pct > _spread_max:   # user-configurable via Settings → Trade Parameters
            log_event("INFO", "bar_eval",
                      f"🟡 [{ticker}] Skipping — bid-ask spread is "
                      f"{_spread_pct*100:.1f}% of mid price "
                      f"(bid=${_c_bid:.2f} ask=${_c_ask:.2f}). "
                      f"Too wide; waiting for tighter liquidity.")
            _skip_log(ticker, "spread_too_wide", strategy=strategy_id, confidence=_top.confidence, direction=direction, tier=_signal_tier,
                     detail=f"spread {_spread_pct*100:.1f}% > {_spread_max*100:.0f}% max (bid ${_c_bid:.2f}/ask ${_c_ask:.2f})")
            return

    # ── R:R gate: block entry if reward-to-risk < 1.6 ─────────────────────────
    # Evaluated BEFORE sending any order.  Both the profit target and stop are
    # slippage-adjusted inside evaluate_rr() so the ratio reflects real fills.
    rr_allowed, rr_audit = _risk.evaluate_rr(
        entry_price              = eff_entry,
        trade_id                 = None,   # assigned after DB insert
        n_contracts              = n_contracts,
        entry_volume_multiplier  = entry_rvol,
    )
    if not rr_allowed and not _reviewed_paid_profile:
        # evaluate_rr() already emitted the Trade_Blocked_Low_RR structured log
        log_event("INFO", "bar_eval",
                  f"🟡 [{ticker}] Skipping this candle — the reward is less than 1.6× the risk "
                  f"at the current price (${eff_entry:.2f}). Waiting for a better entry point.")
        _rr_val = float(rr_audit.get("rr_ratio", 0)) if isinstance(rr_audit, dict) else 0.0
        _skip_log(ticker, "rr_too_low", strategy=strategy_id, confidence=_top.confidence, rr=_rr_val, direction=direction, tier=_signal_tier)
        return
    if not rr_allowed and _reviewed_paid_profile:
        log_event("INFO", "bar_eval",
                  f"🔬 [{ticker}] Reviewed paid-data rule preserves its tested entry; "
                  f"generic R:R diagnostic={rr_audit.get('R_R_Ratio', 'n/a')} is recorded only.")

    # ── Slippage-adjusted profit-target sanity check ──────────────────────────
    # After slippage on both entry and exit, the effective reward must still be
    # positive (i.e., the target price net of exit slip > effective entry price).
    eff_target = _risk.slippage_adjusted_target(eff_entry * (1.0 + _risk.ORB_STAGE1_GAIN))
    if eff_target <= eff_entry:
        logger.warning(
            "profit_target_negative_after_slippage",
            extra={
                "event":      "profit_target_negative_after_slippage",
                "eff_entry":  round(eff_entry, 4),
                "eff_target": round(eff_target, 4),
                "ticker":     ticker,
            },
        )
        return

    # ── AI reasoning layer (phase 2 — decision support) ───────────────────────
    # Runs AFTER every deterministic gate has cleared (R:R, spread, sizing,
    # slippage-adjusted target) and BEFORE signal_only_mode / order placement —
    # the same "all gates cleared, about to commit" moment phase 1's
    # narrate_entry() was scoped for, one step earlier since no order exists
    # yet. Two independent flags gate this: AI_DECISION_SUPPORT_ENABLED must be
    # on for ANY trade to be reviewed; AI_DECISION_SUPPORT_ENABLED_LIVE must
    # ALSO be on for a LIVE trade specifically — so a single flag flip can
    # never expose live capital to this. As of 2026-07-20, ENABLED defaults
    # True (paper trading only) per explicit user decision; ENABLED_LIVE
    # stays False until paper-mode results are reviewed.
    from config import AI_DECISION_SUPPORT_ENABLED, AI_DECISION_SUPPORT_ENABLED_LIVE
    _is_paper_trade = settings.get("paper_trading", True)
    if AI_DECISION_SUPPORT_ENABLED:
        if (not _is_paper_trade) and not AI_DECISION_SUPPORT_ENABLED_LIVE:
            # Live trade but the live-specific switch is off — proceed exactly
            # as if decision support didn't exist, but log why it was skipped.
            log_event("INFO", "bar_eval",
                      f"⚪ [{ticker}] AI decision support skipped — live trade "
                      f"and AI_DECISION_SUPPORT_ENABLED_LIVE is off.")
        else:
            from ai_reasoning.episode_cache import (
                cached_review as _cached_ai_review,
                episode_key as _ai_episode_key,
                remember_review as _remember_ai_review,
                complete_observation as _complete_ai_observation,
            )
            _ds_now = _now_et()
            _ds_cache = _US.setdefault("ai_decision_episode_cache", {})
            _ds_key = _ai_episode_key(ticker, strategy_id, direction)
            _ds_result = _cached_ai_review(_ds_cache, key=_ds_key, observed_at=_ds_now)
            from ai_reasoning.gate_policy import ai_decision_is_enforced
            _ds_enforced = ai_decision_is_enforced(strategy_id)
            if _ds_result is not None:
                logger.debug("Reusing first AI review for active setup episode %s", _ds_key)
            try:
                if _ds_result is not None:
                    raise StopIteration  # clean cached decision; skip indicators and API call
                from trading.mtf_features import (
                    compute_rsi, compute_macd_hist, compute_adx, ema_stack_aligned,
                )
                # NOTE: using _df1m (today's clean 1-minute-only bars), NOT df5.
                # By this point df5 has been reassigned (see the historical-bar
                # augment above) to a concat of historical 5-min bars + today's
                # 1-min bars for RVOL purposes only — splicing two bar periods
                # together breaks the uniform-period assumption every EMA-based
                # indicator here relies on (RSI/MACD/ADX/EMA-stack). _df1m is
                # the single-timeframe frame already sitting in memory with
                # zero extra API calls, so this is free AND more correct.
                _ds_rsi       = compute_rsi(_df1m)
                _ds_macd_hist = compute_macd_hist(_df1m)
                _ds_adx       = compute_adx(_df1m)
                _ds_ema_align = ema_stack_aligned(_df1m, direction)
                # FIX 2026-07-31: this used to hardcode None with a latency
                # justification that no longer holds — apply_mtf_confirmation()
                # already fetched and cached this exact ticker's 1Hour bias
                # earlier in THIS SAME tick (route_signals() call above, via
                # _US["mtf_1h_cache"] / trading/mtf_live_gate.py, 15-min TTL).
                # Reading it here is a cache hit in the common case, not a new
                # blocking API call. Real incident: 3 losing trades today all
                # fired against the 1Hour trend (and mostly against 5Min/15Min
                # too — see mtf_bias_json on those trades), and the AI review
                # layer's own system prompt explicitly asks it to watch for
                # "conflicting multi-timeframe signals" — it just never had
                # the data to do that with. This closes that gap for free.
                try:
                    from trading.mtf_live_gate import get_live_1h_bias
                    _ds_trend_1h = (
                        get_live_1h_bias(
                            alpaca, ticker, direction, _US.setdefault("mtf_1h_cache", {})
                        ) if _ds_enforced else None
                    )
                    if _ds_trend_1h == "neutral":
                        _ds_trend_1h = None   # no signal either way — keep prior "don't mention it" behavior
                except Exception:
                    _ds_trend_1h = None   # never let this optional context block the review call

                _ds_review_kwargs = dict(
                    ticker=ticker, strategy_id=strategy_id, direction=direction,
                    confidence=_top.confidence, rvol=entry_rvol,
                    contract_symbol=contract["symbol"], option_type=opt_type,
                    strike=contract.get("strike"), expiry=contract.get("expiry", ""),
                    n_contracts=n_contracts, entry_price=eff_entry,
                    rr_ratio=rr_audit["R_R_Ratio"], paper=_is_paper_trade,
                    rsi=_ds_rsi, macd_hist=_ds_macd_hist, adx=_ds_adx,
                    ema_aligned=_ds_ema_align, trend_1h_bias=_ds_trend_1h,
                    candidate_id=(getattr(_top, "meta", {}) or {}).get("shadow_candidate_id"),
                )
                if _ds_enforced:
                    from ai_reasoning.decision_support import review_entry
                    _ds_result = review_entry(enforced=True, **_ds_review_kwargs)
                    _remember_ai_review(
                        _ds_cache, key=_ds_key, observed_at=_ds_now, result=_ds_result,
                    )
                else:
                    from ai_reasoning.decision_support import observe_entry_async
                    from ai_reasoning.episode_cache import ObservationScheduled
                    _ds_marker = ObservationScheduled()
                    _remember_ai_review(
                        _ds_cache, key=_ds_key, observed_at=_ds_now, result=_ds_marker,
                    )

                    def _finish_ai_observation(result, *, cache=_ds_cache, key=_ds_key, marker=_ds_marker):
                        # Preserve a clean opinion for repeated detections;
                        # failed work is removed so a later tick can retry.
                        _complete_ai_observation(
                            cache, key=key, marker=marker, result=result,
                        )

                    observe_entry_async(on_complete=_finish_ai_observation, **_ds_review_kwargs)
                    _ds_result = _ds_marker
            except StopIteration:
                pass
            except Exception as _ds_ex:
                # review_entry() already fails open internally — this outer
                # try/except is a second, independent safety net in case the
                # import or the MTF feature computation above raises before
                # review_entry() is even reached. Never let this block a
                # trade the deterministic system already approved.
                logger.warning("AI decision support call failed (non-fatal, trade proceeds): %s", _ds_ex)
                _ds_result = None

            from ai_reasoning.gate_policy import ai_decision_effect
            _ds_effect, _ds_effect_contracts = ai_decision_effect(
                strategy_id,
                _ds_result.action if _ds_result is not None else "approve",
                _ds_result.size_multiplier if _ds_result is not None else 1.0,
                n_contracts,
            )
            if _ds_result is not None and _ds_effect == "observe":
                # Keep collecting the model's counterfactual opinion, linked
                # to this candidate's later option marks, without letting an
                # unvalidated model rewrite a tuned deterministic strategy.
                log_event(
                    "INFO", "bar_eval",
                    f"🟣 [{ticker}] AI review recorded for calibration only — "
                    f"{_ds_result.action.replace('_', ' ')} was NOT applied. "
                    f"{_ds_result.rationale or 'No rationale given.'}",
                )
            elif _ds_result is not None and _ds_effect == "veto":
                log_event("INFO", "bar_eval",
                          f"🟣 [{ticker}] AI decision support VETO — "
                          f"{_ds_result.rationale or 'no reason given'}")
                _skip_log(ticker, "ai_decision_veto", strategy=strategy_id, confidence=_top.confidence, tier=_signal_tier,
                         direction=direction, detail=_ds_result.rationale or "AI review declined, no rationale given")
                return
            elif _ds_result is not None and _ds_effect == "reduce_size":
                if _ds_effect_contracts < n_contracts:
                    log_event("INFO", "bar_eval",
                              f"🟣 [{ticker}] AI decision support reduced size: "
                              f"{n_contracts} → {_ds_effect_contracts} contracts. {_ds_result.rationale or ''}")
                    n_contracts = _ds_effect_contracts
                    _US["last_eval_contracts"] = n_contracts
                # else: multiplier didn't actually change the integer contract
                # count (e.g. 2c × 0.9 still floors to 2) — nothing to apply.

    # ── Authoritative order intent ────────────────────────────────────────────
    # The earlier contract preview is explanatory and may be captured before
    # every gate has cleared.  This is the actual executable decision: exact
    # OCC contract, final quantity, bounded entry prices, and exit plan.  The
    # SAME intent is persisted for the UI and passed to Alpaca below.
    _order_mid, _order_ask = entry_limit_prices(
        ask=ask_price, midpoint=_c_mid, v2_paper_pilot=_v2_paid_parity,
    )
    _candidate_id = None
    if isinstance(_opportunity_context, dict):
        _candidate_meta = _opportunity_context.get("strategy_meta")
        if isinstance(_candidate_meta, dict):
            _candidate_id = _candidate_meta.get("shadow_candidate_id")
        _intent_now = _now_et()
        _order_intent = {
            "intent_id": uuid4().hex,
            "status": "ready",
            "created_at": _intent_now.isoformat(),
            "expires_at": (_intent_now + timedelta(minutes=2)).isoformat(),
            "candidate_id": _candidate_id,
            "ticker": ticker,
            "strategy_id": _US.get("last_strategy_id", strategy_id),
            "direction": direction,
            "option_type": opt_type,
            "contract_symbol": contract.get("symbol"),
            "strike": contract.get("strike"),
            "expiry": contract.get("expiry"),
            "quote_source": "tradier_production",
            "quote_bid": round(float(_c_bid), 4),
            "quote_ask": round(float(_c_ask), 4),
            "quote_mid": round(float(_c_mid), 4),
            "quote_latency_ms": _quote_latency_ms,
            "quote_received_at": contract.get("quote_received_at"),
            "quote_bid_time_ms": contract.get("quote_bid_time_ms"),
            "quote_ask_time_ms": contract.get("quote_ask_time_ms"),
            "working_limit": round(float(_order_mid), 4),
            "step_limit": round(float(_order_ask), 4) if _order_ask is not None else None,
            "maximum_entry_price": round(float(eff_entry), 4),
            "quantity": int(n_contracts),
            "user_approved_match": _user_approved_match,
            "estimated_notional": round(float(eff_entry) * int(n_contracts) * 100, 2),
            "rr_ratio": rr_audit.get("R_R_Ratio"),
            "exit_plan": _opportunity_context.get("exit_plan"),
        }
        _opportunity_context["order_intent"] = _order_intent
        try:
            from database.option_quotes import promote_candidate_entry_quote
            if _candidate_id:
                promote_candidate_entry_quote(
                    candidate_id=str(_candidate_id),
                    contract_symbol=str(contract.get("symbol") or ""),
                    observed_at=_intent_now,
                    quote=contract,
                    source="tradier_authoritative_order_intent",
                )
        except Exception:
            logger.debug("authoritative candidate quote promotion failed for %s", ticker, exc_info=True)
        try:
            from shadow_ledger import snapshot_candidate_plan
            snapshot_candidate_plan(_opportunity_context)
        except Exception:
            logger.debug("authoritative order intent snapshot failed for %s", ticker, exc_info=True)
    else:
        _order_intent = {
            "intent_id": uuid4().hex,
            "status": "ready",
            "candidate_id": None,
        }

    # ── Signal-only mode gate ─────────────────────────────────────────────────
    # All quality checks passed. If signal_only_mode is on, broadcast the alert
    # but skip execution — user enters the trade manually in their broker.
    if collection_only:
        _order_intent["status"] = "maintenance_observed_only"
        _order_intent["resolved_at"] = _now_et().isoformat()
        if isinstance(_opportunity_context, dict):
            try:
                snapshot_candidate_plan(_opportunity_context)
            except Exception:
                logger.debug("collection-only intent snapshot failed for %s", ticker, exc_info=True)
        log_event("INFO", "trading_logic",
                  f"🔬 [{ticker}] Research record only — maintenance prevents every order and exit.")
        # The scanner reached a complete, actionable plan, but maintenance
        # deliberately prevented an order.  Resolve the candidate so Scanner
        # Opportunities says exactly that instead of leaving it "pending".
        _log_journal(
            ticker, strategy_id, direction, _top.confidence,
            outcome="observed_only", reason_code="maintenance_collection_only",
            reason_detail="Maintenance collection mode kept this complete setup from placing an order.",
            context=_opportunity_context, tier=_signal_tier,
        )
        return

    if settings.get("signal_only_mode", False):
        _order_intent["status"] = "signal_only"
        _order_intent["resolved_at"] = _now_et().isoformat()
        if isinstance(_opportunity_context, dict):
            try:
                snapshot_candidate_plan(_opportunity_context)
            except Exception:
                logger.debug("signal-only intent snapshot failed for %s", ticker, exc_info=True)
        _s1_disp = round(eff_entry * 1.5, 2)
        log_event("INFO", "trading_logic",
                  f"📡 [{ticker}] MANUAL SIGNAL — {opt_type.upper()} "
                  f"${contract.get('strike', '')} exp {contract.get('expiry', '')} "
                  f"| {n_contracts}c @ ${eff_entry:.2f} → ${_s1_disp:.2f} "
                  f"[{strategy_id}] — Signal-Only mode is ON. Enter this trade yourself.")
        # This is intentionally not an order.  Still save the complete plan
        # so the learner can see the exact contract, size, and intended exit.
        _log_journal(
            ticker, strategy_id, direction, _top.confidence,
            outcome="observed_only", reason_code="signal_only_mode",
            reason_detail="Manual signal only: all entry checks cleared, but Signal-Only mode did not place an order.",
            context=_opportunity_context, tier=_signal_tier,
        )
        return

    # ── Place order ───────────────────────────────────────────────────────────
    # Use the raw ask_price for the actual limit order sent to the broker
    # (eff_entry is our internal worst-case planning price, not the bid we send).
    order = None

    # Always route through the broker — the paper/live destination is controlled
    # by ALPACA_BASE_URL in .env (paper-api.alpaca.markets vs api.alpaca.markets).
    _entry_key = (contract["symbol"], _now_et().strftime("%H:%M"))
    if _US.get("_last_order_key") == _entry_key:
        _order_intent["status"] = "duplicate_blocked"
        _order_intent["resolved_at"] = _now_et().isoformat()
        if isinstance(_opportunity_context, dict):
            try:
                snapshot_candidate_plan(_opportunity_context)
            except Exception:
                logger.debug("duplicate-blocked intent snapshot failed for %s", ticker, exc_info=True)
        logger.warning(
            "Duplicate order blocked — same contract+minute as last order: %s",
            contract["symbol"],
        )
        return

    if paper:
        logger.info("[PAPER] BUY %d %s @ ask=$%.4f eff_entry=$%.4f (%s)",
                    n_contracts, contract["symbol"], ask_price, eff_entry, direction)
    # Stamp the key BEFORE placing so a concurrent tick that reaches here
    # in the same minute sees the lock immediately.
    _US["_last_order_key"] = _entry_key
    # The normal path seeks price improvement at midpoint then crosses to ask.
    # The V2 paid study bought at ask, so its paper cohort crosses directly at
    # ask instead.  Otherwise a favorable midpoint fill could be mislabeled as
    # confirmation of the historical ask-to-bid evidence.
    _spread_save = round(((_order_ask or _order_mid) - _order_mid) * n_contracts * 100, 2)
    if _v2_paid_parity:
        log_event("INFO", "order",
                  f"🔬 [{ticker}] V2 paper study entry at ask ${_order_mid:.2f} "
                  f"for {n_contracts} contract(s) — matches the paid historical fill rule.")
    else:
        log_event("INFO", "order",
                  f"💡 [{ticker}] Limit order at mid ${_order_mid:.2f} "
                  f"(ask ${_order_ask:.2f}) — potential saving ${_spread_save:.2f} "
                  f"on {n_contracts} contract(s). Will step up to ask if not filled in 5s.")
    _entry_wait_seconds = _entry_order_wait_seconds(
        has_open_positions=bool(open_trades),
    )
    _order_intent["working_window_seconds"] = _entry_wait_seconds
    try:
        from trading.annotations import snapshot_annotations
        _durable_annotations = snapshot_annotations(ticker)
    except Exception:
        _durable_annotations = None
    order = alpaca.place_option_order(
        symbol          = contract["symbol"],
        qty             = n_contracts,
        side            = "buy",
        order_type      = "limit",
        limit_price     = _order_mid,
        step_to_price   = _order_ask,
        max_acceptable_price = eff_entry,
        allow_market_fallback = False,
        position_intent = "buy_to_open",
        # Rest the exact analyzed contract through most of the next one-minute
        # candle. It may step toward, but never above, the approved ceiling.
        max_wait_seconds = _entry_wait_seconds,
        price_authority = "tradier",
        order_context   = {
            "ticker": ticker,
            "strategy_id": _US.get("last_strategy_id", strategy_id),
            "candidate_id": _candidate_id,
            "intent_id": _order_intent["intent_id"],
            "quote_source": "tradier_production",
            "quote_bid": _c_bid,
            "quote_ask": _c_ask,
            "quote_mid": _c_mid,
            "quote_latency_ms": _quote_latency_ms,
            "quote_received_at": contract.get("quote_received_at"),
            "quote_bid_time_ms": contract.get("quote_bid_time_ms"),
            "quote_ask_time_ms": contract.get("quote_ask_time_ms"),
            "stop_factor": 1.0 - _risk.dynamic_stop_pct(_now_et(), _now_et()),
            "target_factor": 1.0 + _risk.ORB_STAGE1_GAIN,
            "direction": direction,
            "confidence": float(_top.confidence),
            "entry_record": {
                "ticker": ticker, "contract_symbol": contract["symbol"],
                "option_type": opt_type, "strike": contract["strike"],
                "expiry": contract.get("expiry", ""), "paper": int(paper),
                "strategy_id": _US.get("last_strategy_id", strategy_id),
                "tier": _signal_tier, "candidate_id": _candidate_id,
                "broker_account_id": settings.get("active_broker_account_id") or None,
                "entry_reason": f"ORB {direction} | R:R={rr_audit['R_R_Ratio']}",
                "annotations_json": _durable_annotations,
            },
        },
    )

    # FIX S1: Only record trade if order actually filled
    if order is None:
        if getattr(alpaca, "last_order_outcome", None) in {
            "recovery_pending", "reconciled_retry_next_tick", "intent_already_processed",
        }:
            _order_intent["status"] = "recovery_pending"
            _log_journal(
                ticker, strategy_id, direction, _top.confidence,
                outcome="blocked", reason_code="broker_fill_unconfirmed",
                reason_detail="Checking the original broker order and journal before another order; not a missed-price verdict.",
                context=_opportunity_context, tier=_signal_tier,
            )
            return
        _order_intent["status"] = "price_not_reached"
        _order_intent["resolved_at"] = _now_et().isoformat()
        try:
            from shadow_ledger import snapshot_candidate_plan
            snapshot_candidate_plan(_opportunity_context)
        except Exception:
            logger.debug("unfilled order intent snapshot failed for %s", ticker, exc_info=True)
        logger.error(
            "order_not_recorded",
            extra={
                "event": "order_not_recorded",
                "ticker": ticker,
                "contract_symbol": contract["symbol"],
                "direction": direction,
                "reason": "broker returned None — fill not confirmed",
            },
        )
        _log_journal(
            ticker, strategy_id, direction, _top.confidence,
            # This is a deliberate no-chase expiry, not a broker failure or a
            # strategy gate.  Keep the lifecycle stopped because no position
            # exists, but preserve the true execution reason for the UI and
            # fill-quality scorecard.
            outcome="blocked", reason_code="entry_price_not_reached",
            reason_detail=(
                f"The exact analyzed contract rested at the approved limit for "
                f"{_entry_wait_seconds} seconds, "
                "but the market never offered a fill at or below the maximum entry price."
            ),
            context=_opportunity_context, tier=_signal_tier,
        )
        return

    # Prefer the broker's actual average fill. Some adapters provide the
    # normalized confirmed field, while others return Alpaca's native
    # `filled_avg_price`. Only fall back to the analyzed ask when neither is
    # present, so journal P&L cannot silently use the planned quote as a fill.
    confirmed_price = _confirmed_entry_price(order, ask_price)
    entry_utc       = _now_et()   # tz-aware ET — stored as ET ISO in DB
    _order_intent.update({
        "status": "filled",
        "resolved_at": entry_utc.isoformat(),
        "broker_order_id": str(order.get("id") or "") or None,
        "execution_attempt_id": order.get("execution_attempt_id"),
        "confirmed_fill_price": round(float(confirmed_price), 4),
    })

    # FIX 2026-07-20 (Alpaca fills audit): broker.py's _wait_for_fill now
    # always reports the REAL filled_qty (previously a partial fill either
    # vanished as None or got silently recorded at the full REQUESTED size).
    # Record the position at the size that ACTUALLY filled, not the size we
    # asked for — otherwise the DB shows more contracts open than Alpaca
    # really holds, which throws off risk sizing and P&L on this trade.
    _filled_qty = int(order.get("filled_qty", n_contracts))
    if _filled_qty != n_contracts:
        log_event(
            "WARNING", "order",
            f"🟡 [{ticker}] Only {_filled_qty} of {n_contracts} requested "
            f"contract(s) actually filled — recording the position at the "
            f"REAL size, not the requested size."
        )
        logger.warning(
            "partial_fill_entry: symbol=%s requested=%d filled=%d",
            contract["symbol"], n_contracts, _filled_qty,
        )
        n_contracts = _filled_qty
    if n_contracts < 1:
        logger.error(
            "partial_fill_zero_entry",
            extra={"event": "partial_fill_zero_entry", "ticker": ticker,
                   "contract_symbol": contract["symbol"]},
        )
        log_event("ERROR", "order",
                  f"🔴 [{ticker}] Order reported as filled but 0 contracts "
                  f"actually filled — no position recorded.")
        _log_journal(
            ticker, strategy_id, direction, _top.confidence,
            outcome="blocked", reason_code="broker_fill_unconfirmed",
            reason_detail="The broker reported zero contracts filled, so no position was recorded.",
            context=_opportunity_context, tier=_signal_tier,
        )
        return

    # ── Record to database ────────────────────────────────────────────────────
    # Compute stop/target at entry — stored so the chart can show the position overlay
    _stop_px   = round(_risk.dynamic_stop_price(confirmed_price, entry_utc), 4)
    _target_px = round(_risk.stage1_exit_price(confirmed_price), 4)

    # Snapshot the bot's own reasoning (FVG zones, BOS/TREND_CONT levels, the
    # signal marker that fired) onto the trade so Journal's replay can show
    # WHY this entry happened on any future day — the live annotation buffer
    # this reads from is capped and gets overwritten as the session goes on,
    # so this is the only durable copy. Wrapped defensively: a bad snapshot
    # must never block recording the trade itself.
    try:
        from trading.annotations import snapshot_annotations  # noqa: PLC0415
        _entry_annotations_json = snapshot_annotations(ticker)
    except Exception:
        logger.warning("Entry annotation snapshot failed for %s — trade will save with no annotations", ticker, exc_info=True)
        _entry_annotations_json = None

    _candidate_id = None
    if isinstance(_opportunity_context, dict):
        _candidate_meta = _opportunity_context.get("strategy_meta")
        if isinstance(_candidate_meta, dict):
            _candidate_id = _candidate_meta.get("shadow_candidate_id")
    trade_id = order.get("accounted_trade_id") or insert_trade(
        ticker          = ticker,
        contract_symbol = contract["symbol"],
        option_type     = opt_type,
        strike          = contract["strike"],
        expiry          = contract.get("expiry", ""),
        contracts       = n_contracts,
        entry_price     = confirmed_price,
        entry_time      = entry_utc,
        entry_reason    = f"ORB {direction} | R:R={rr_audit['R_R_Ratio']}",
        paper           = paper,
        strategy_id     = _US.get("last_strategy_id", "UNKNOWN"),
        stop_price      = _stop_px,
        target_price    = _target_px,
        annotations_json= _entry_annotations_json,
        tier            = _signal_tier,
        broker_account_id=settings.get("active_broker_account_id") or None,
        candidate_id     = _candidate_id,
        entry_order_id   = str(order.get("id") or "") or None,
        entry_fill_time  = order.get("filled_at") or entry_utc,
    )
    _order_intent["trade_id"] = trade_id
    try:
        from shadow_ledger import snapshot_candidate_plan
        snapshot_candidate_plan(_opportunity_context)
    except Exception:
        logger.debug("filled order intent snapshot failed for trade %s", trade_id, exc_info=True)
    try:
        from database import link_broker_order_to_trade
        link_broker_order_to_trade(
            str(order.get("id") or ""), trade_id, link_kind="entry",
        )
    except Exception:
        logger.warning("entry order-flow link failed for trade %s", trade_id, exc_info=True)

    # Capture the executable chain quote alongside every PAPER entry.  This is
    # evidence for later execution-fidelity research, not an input to this
    # order and never a reason to alter/deny a trade that already filled.
    if paper:
        try:
            from database import record_paper_option_quote
            record_paper_option_quote(
                trade_id=trade_id,
                contract_symbol=contract["symbol"],
                observation_kind="entry",
                observed_at=entry_utc,
                quote={
                    "bid": contract.get("bid"), "ask": contract.get("ask"),
                    "mid": _c_mid, "last": contract.get("last"),
                },
                source="tradier_chain",
                fill_price=confirmed_price,
            )
        except Exception:
            logger.warning("paper entry quote capture failed for trade %s", trade_id, exc_info=True)

    # Journal the final 'entered' outcome — see signal_journal.py. Wrapped
    # defensively: a journal write must never be allowed to affect a trade
    # that already went through.
    try:
        # Use the progressively enriched plan created before placement rather
        # than a smaller second context.  The same candidate now links all of
        # signal → selected contract → actual fill → intended exit.
        if isinstance(_opportunity_context, dict):
            _opportunity_context["planned_quantity"] = int(n_contracts)
            _entry_contract = _opportunity_context.setdefault("contract", {})
            if isinstance(_entry_contract, dict):
                _entry_contract["research_eligibility"] = _sel_info.get("research_eligibility")
        _journal_id = _log_journal(ticker, _US.get("last_strategy_id", "UNKNOWN"), direction, _top.confidence,
                     outcome="entered", reason_detail=f"R:R={rr_audit['R_R_Ratio']}", trade_id=trade_id,
                     context=_opportunity_context, tier=_signal_tier)
        if _journal_id is None:
            logger.error(
                "signal_trade_link_missing: trade_id=%s ticker=%s strategy=%s",
                trade_id, ticker, _US.get("last_strategy_id", "UNKNOWN"),
            )
        else:
            from database import audit_trade_lineage
            _lineage_missing = audit_trade_lineage(trade_id)
            if _lineage_missing:
                logger.error(
                    "trade_lineage_incomplete: trade_id=%s missing=%s",
                    trade_id, ",".join(_lineage_missing),
                )
    except Exception:
        logger.exception("signal_trade_link_write_failed: trade_id=%s", trade_id)

    # Re-run R:R audit with real trade_id — final structured log record
    _risk.evaluate_rr(
        entry_price              = confirmed_price,
        trade_id                 = trade_id,
        n_contracts              = n_contracts,
        entry_volume_multiplier  = entry_rvol,
    )

    # NEW (MAX_CONCURRENT_POSITIONS): re-read ALL open trades from the DB so
    # open_trades/open_trade reflect this new position alongside any other
    _US["open_trades"]      = get_open_trades()
    _US["open_trade"]       = _US["open_trades"][0] if _US["open_trades"] else None
    _US["status"]           = "in_trade"
    _US["orb_triggered"]    = True   # blocks further entries unless flip armed
    _US["last_direction"]   = direction
    # Consume the flip token — after entering the flip trade, no more re-entries
    _US["flip_eligible"]    = False
    _US["flip_direction"]   = None
    _US["flip_ticker"]      = None
    # Fix 2: mark this ticker as having had an ORB entry this session so the
    # bot won't re-enter the same ORB breakout after the trade closes.
    _US.setdefault("orb_entered_today", set()).add(ticker)

    # ── Per-position live-management state (NEW — MAX_CONCURRENT_POSITIONS) ──
    # Each open trade gets its OWN peak/stage/stop tracking so a 2nd concurrent
    # position's stage/stop progress can never overwrite the 1st's (and vice
    _US["positions"][trade_id] = {
        "peak_price":                confirmed_price,
        "entry_time":                entry_utc.isoformat(),
        "stage1_done":               False,
        "stage1_be_price":           None,
        "current_stop_pct":          _risk.ORB_STOP_PCT,
        "struct_stop_price":         None,   # filled in just below if structural stop applies
        "current_option_price":      confirmed_price,
        "current_option_price_time": _now_et().strftime("%H:%M:%S"),
        "last_position_narration_minute": None,
    }

    # ── Structural stop: convert an approved setup's bar level to option price ─
    # We compute the implied option stop once at entry (delta approx 0.40) so
    _signal_meta      = _top.meta if hasattr(_top, "meta") and _top.meta else {}
    _entry_bar_stop   = _signal_meta.get("entry_bar_high") or _signal_meta.get("entry_bar_low")
    _struct_stop_opt  = None
    if _entry_bar_stop is not None:
        try:
            _underlying_now  = float(df5["close"].iloc[-1])
            _struct_stop_opt = _risk.structural_stop_from_level(
                confirmed_price, _underlying_now, float(_entry_bar_stop))
            logger.info(
                "structural_stop_set ticker=%s entry_bar_level=%.4f "
                "underlying_now=%.4f option_stop=%.4f",
                ticker, _entry_bar_stop, _underlying_now, _struct_stop_opt,
            )
        except Exception as _sse:
            logger.warning("structural_stop_from_level failed: %s", _sse)
    _US["positions"][trade_id]["struct_stop_price"] = _struct_stop_opt

    persist_peak_price(trade_id, confirmed_price)

    # ── MTF alignment snapshot (teaching overlay, best-effort) ────────────────
    # Runs AFTER the trade is already recorded and all critical position state
    # above is set — 3 extra API calls (5Min/15Min/1Hour) must never delay
    # recording the trade itself or risk the entry in any way. Fully wrapped;
    # a failure here just means the Journal's MTF heat map shows "unknown"
    # for this trade, nothing more.
    try:
        from trading.mtf_features import compute_mtf_alignment
        from database import save_mtf_bias
        import json as _json
        _mtf_bias = compute_mtf_alignment(alpaca, ticker, direction, df_1m=df5)
        save_mtf_bias(trade_id, _json.dumps(_mtf_bias))
    except Exception:
        logger.warning("MTF alignment snapshot failed for trade %d — Journal will show 'unknown'", trade_id, exc_info=True)

    # Bind trade context so all subsequent log lines include trade metadata
    try:
        from logger_config import get_trade_logger
        set_user_trade_log(get_trade_logger(
            ticker=ticker,
            contract_symbol=contract["symbol"],
            session_id=str(trade_id),
        ))
    except Exception:
        set_user_trade_log(logger)
    _trade_log = get_user_trade_log()

    # Determine risk tier label for this trade
    _active_risk_pct = _risk.effective_risk_pct(balance)
    _tier_label = (
        "Tier4_5pct" if _active_risk_pct >= BOOTSTRAP_RISK_PCT else
        "Tier3_3pct" if _active_risk_pct >= _GMT_TL else
        "Tier2_2pct" if _active_risk_pct >= _MTT_TL else
        "Tier1_1pct"
    )

    _trade_log.info(
        "trade_opened",
        extra={
            "event":                   "trade_opened",
            # ── Mandatory 4-field audit signature ─────────────────────────
            "Trade_ID":                trade_id,
            "Risk_Tier_Used":          _tier_label,
            "R_R_Ratio":               rr_audit["R_R_Ratio"],
            "Entry_Volume_Multiplier": round(entry_rvol, 2),
            "Strategy_ID":             _US.get("last_strategy_id", "UNKNOWN"),
            # ── Full trade context ─────────────────────────────────────────
            "ticker":           ticker,
            "contract_symbol":  contract["symbol"],
            "option_type":      opt_type,
            "n_contracts":      n_contracts,
            "entry_price":      round(confirmed_price, 4),
            "eff_entry":        round(rr_audit["eff_entry"], 4),
            "stop_loss":        round(_risk.dynamic_stop_price(confirmed_price, entry_utc), 4),
            "stop_pct":         round(_risk.ORB_STOP_PCT * 100, 1),
            "stage1_target":    round(_risk.stage1_exit_price(confirmed_price), 4),
            "eff_target":       round(rr_audit["eff_target"], 4),
            "Expected_Win":     rr_audit["Expected_Win"],
            "Expected_Loss":    rr_audit["Expected_Loss"],
            "paper":            paper,
            "entry_time_et":    entry_utc.isoformat(),
        },
    )

    # ── Human-readable entry narrative for the Audit Log ─────────────────────
    # This is the 🟢 row the user sees: plain-English summary of WHY we entered,
    # WHERE the stops are, and WHAT we're targeting — no raw numbers or codes.
    try:
        _strat_name = {
            "V2_ORB_PULLBACK": "Opening-Range Pullback",
            "V2_SPY_TREND_CONT": "SPY Trend Continuation",
            "V2_SPY_AFTERNOON_FVG": "SPY Afternoon Fair Value Gap",
            "V2_FAILED_OR_BREAK_VWAP_REVERSION": "SPY Failed-Range Recovery",
            "V2_TSLA_TWO_LEG_TREND_PULLBACK": "TSLA Two-Leg Trend Pullback",
        }.get(_US.get("last_strategy_id", "UNKNOWN"), "Reviewed strategy")
        _stop_px  = round(_risk.dynamic_stop_price(confirmed_price, entry_utc), 2)
        _tgt_px   = round(_risk.stage1_exit_price(confirmed_price), 2)
        _mode_tag = "[PAPER] " if paper else ""
        log_event(
            "INFO", "trading_logic",
            f"🟢 {_mode_tag}ENTRY — Buying {ticker} {opt_type.upper()} "
            f"({n_contracts} contract{'s' if n_contracts > 1 else ''} @ ${confirmed_price:.2f}) "
            f"via {_strat_name}. "
            f"Stop: ${_stop_px:.2f} · Target: ${_tgt_px:.2f} · "
            f"R:R: {rr_audit['R_R_Ratio']} · Volume: {entry_rvol:.1f}× normal",
        )
    except Exception:
        pass  # never let narrative logging crash the trade

    # ── AI reasoning layer (phase 1 — narration only) ────────────────────────
    # Fire-and-forget: narrate_entry() spawns a daemon thread and returns
    # immediately (or no-ops instantly if AI_REASONING_ENABLED is off), so
    # this can never add latency to the trading loop's next tick. Purely
    # informational — has zero effect on the trade that already executed.
    try:
        from ai_reasoning.narrator import narrate_entry
        narrate_entry(
            ticker           = ticker,
            strategy_id      = _US.get("last_strategy_id", "UNKNOWN"),
            direction        = direction,
            confidence       = _top.confidence,
            rvol             = entry_rvol,
            contract_symbol  = contract["symbol"],
            option_type      = opt_type,
            strike           = contract.get("strike"),
            expiry           = contract.get("expiry", ""),
            n_contracts      = n_contracts,
            entry_price      = confirmed_price,
            stop_price       = _stop_px,
            target_price     = _tgt_px,
            rr_ratio         = rr_audit["R_R_Ratio"],
            paper            = paper,
            trade_id         = trade_id,
            signal_meta      = _signal_meta,
        )
    except Exception as _ai_ex:
        logger.debug("ai_reasoning narrate_entry dispatch failed (non-fatal): %s", _ai_ex)
