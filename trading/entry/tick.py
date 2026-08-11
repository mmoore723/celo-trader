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

import pandas as pd
import pytz as _pytz

# ── Project imports ──────────────────────────────────────────────────────
from config import (
    TRADIER_ACCOUNT_ID,
    LIQUID_TICKERS,
    STARTING_CAPITAL,
    MIN_CONTRACT_COST, MAX_CONTRACT_COST,
    EARNINGS_BLACKOUT_DAYS,
    get_settings, get_risk_tier,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT as _GMT_TL, MID_TIER_RISK_PCT as _MTT_TL,
    MAX_CONCURRENT_POSITIONS,
    SESSION_HARD_CUTOFF_HM,
    STAGE2_TRAIL_PCT,
    get_bot_state_path,
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
from trading.entry.contract import select_contract, select_v2_orb_contract
from trading.v2_orb_paper_execution import entry_limit_prices, include_tsla_when_v2_pilot_enabled
from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
from trading.entry.skip_log import _skip_log
from trading.opportunity_scheduler import clear as _clear_opportunity_window
from trading.opportunity_scheduler import due_ticker as _opportunity_due_ticker
from trading.opportunity_scheduler import select as _select_opportunity_signal

logger = logging.getLogger("celo_trader.trading_logic")

# NOTE: _trade_log / _risk module-level globals were removed in a prior
# session — see trading.state.get_user_trade_log()/get_user_risk(). _tick()
# resolves both fresh each call instead of reading module globals.


# ── Per-tick evaluation ───────────────────────────────────────────────────────

def _tick(alpaca: AlpacaClient, tradier: TradierClient) -> None:
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
    from datetime import date as _date
    _today_str = _date.today().isoformat()
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
        # Check whether the market is GENUINELY closed vs. an API glitch.
        # Alpaca's /v2/clock endpoint occasionally returns False during live
        _now_hm_tick = _now_et().hour * 60 + _now_et().minute
        _genuinely_closed = _now_hm_tick >= 16 * 60 or _now_hm_tick < 9 * 60 + 30

        if not _genuinely_closed:
            # API says closed but local clock says we're mid-session.
            # Override market_open and fall through to normal tick processing.
            market_open = True
            _US["market_open"] = True
            logger.debug("is_market_open()=False overridden — local ET %02d:%02d is "
                         "within session (9:30–16:00); API glitch assumed",
                         _now_hm_tick // 60, _now_hm_tick % 60)
        else:
            # Genuinely outside market hours — do the full closed-session write
            # and return early so no trading logic runs overnight / pre-market.
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
                _json.dump({
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
                }, open(_state_path, "w"))
            except Exception:
                pass
            return   # ← only exits here when GENUINELY closed

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
        _json.dump({
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
        }, open(_state_path, "w"))
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
                                    bid_price=_cbid)
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
        # would have blocked an order.  No execution path is enabled below.
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

    # The V2 research hypothesis is TSLA-only.  Add TSLA to the rotation only
    # when that exact paper pilot has passed both explicit enable switches.
    # This is observation coverage, not a bypass of the normal entry gates.
    _v2_pilot_approved = {
        str(strategy_id).strip().upper()
        for strategy_id in settings.get("validated_strategy_ids", [])
        if str(strategy_id).strip()
    }
    _v2_pilot_enabled = bool(settings.get("paper_trading", True) and (
        (settings.get("strategy_orb_pullback_v2_enabled", False) and "V2_ORB_PULLBACK" in _v2_pilot_approved)
        or (settings.get("strategy_trend_cont_v2_enabled", False) and "V2_TREND_CONT" in _v2_pilot_approved)
    ))
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
    if _v2_pilot_enabled and "TSLA" not in _BL:
        _with_tsla = include_tsla_when_v2_pilot_enabled(watchlist, v2_paper_pilot=True)
        if _with_tsla != watchlist:
            watchlist = _with_tsla
            _US["scan_watchlist"] = watchlist
            logger.info("v2_paper_pilot_added_tsla_to_watchlist")

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
    if _due_ticker:
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
    # No strategy enters by default. It must be promoted after passing real
    # option quote validation; prior backtests remain research evidence only.
    # Historical notes retained below explain why the legacy set is not active.
    # 2026-07-15/16 backtest audits (SPY/QQQ/NVDA, 3mo, post-ADX-gate):
    #   TREND_CONT re-enabled — +$39-41/trade, 58% WR, consistent across runs.
    #   Same 3-month sample both times though — re-audit on 6mo before
    #   trusting this as fully confirmed.
    #   VWAP_PB stays off — even after the 5-gate rework (blowthrough,
    #   touch proximity, slope, ADX) it's still -$99/trade. A/B-tested a
    #   proposed loosening (ab_test_vwap_pb.py): it did WORSE, -$168/trade.
    #   AFT_REV added to disabled list — 0-for-4 across runs, -$127/trade,
    #   75% of exits hit the 60-min time_box (see diag_aft_rev.py). Needs a
    #   coherent rework (not just parameter loosening) before re-testing.
    #
    # 2026-07-18 audit fix: IFVG (strategies/ifvg.py) was fully implemented and
    # listed in strategy_router.ACTIVE_STRATEGIES, but was MISSING from this
    # tuple entirely — meaning it could never appear in `_enabled` and never
    # fired live or in paper, despite api/models.py's Settings.ifvg_enabled
    # field already defaulting True. Added below, defaulting to True (on) per
    # explicit user decision 2026-07-18 — this is a first live test of this
    # strategy, not a re-enable; it has no prior live/paper track record.
    #
    # 2026-07-20: VWAP_PB and AFT_REV flipped back to True per explicit user
    # decision. Their prior -$99/trade and -$127/trade (0-for-4) audit
    # numbers were generated BEFORE two trade-recording bug fixes (7d31c52
    # "paper-mode fill confirmation fabricated fake trades", 07-17; 2c350de
    # "close_trade_by_id() false-positive", 07-16) — those numbers are not
    # trustworthy and should not have been driving an off-by-default policy.
    # Stated policy going forward: every strategy is ON by default; the user
    # opts individual ones OFF via Settings, not the other way around.
    _STRAT_DEFAULTS = {
        "strategy_orb_enabled":   False,
        "strategy_bos_enabled":   False,
        "strategy_vwap_enabled":  False,
        "strategy_fvg_enabled":   False,
        "strategy_ifvg_enabled":  False,
        "strategy_chan_enabled":  False,
        "strategy_tcont_enabled": False,
        "strategy_aft_enabled":   False,
        # MID_BRK 2026-07-23 — disabled after the professional-strategy-alignment
        # audit: 13 distinct backtested configurations (4 structural-stop modes,
        # 2 exit-complexity variants, 4 RVOL ceilings, session-window extension,
        # ADX-gate removal, a data-targeted best-hour window), all negative
        # expectancy, -$44 to -$75/trade. The setup was never modeled on a real
        # professional strategy — it traded the exact midday window sources say
        # to build reference levels in, not trade directly. See CLAUDE.md rule 9
        # research + run_full_audit.py history for the full trail.
        "strategy_mid_enabled":   False,
        # GAP_GO — flipped to True 2026-07-31 per explicit user decision,
        # same pattern as VWAP_PB/AFT_REV above. Still has no backtest track
        # record of its own (built from published sources, never run through
        # this bot's backtester) — that risk is accepted, not resolved.
        "strategy_gapgo_enabled": False,
        # LIQ_SWEEP 2026-07-31 — new strategy, see strategies/liquidity_sweep.py.
        # ON by default per explicit user decision. Zero backtest history —
        # same accepted risk as GAP_GO above.
        "strategy_liqsweep_enabled": False,
    }
    _approved_strategy_ids = {
        str(strategy_id).strip().upper()
        for strategy_id in _strat_cfg.get("validated_strategy_ids", [])
        if str(strategy_id).strip()
    }
    _enabled: set[str] = {
        sid for sid, key in (
            ("INST_ORB",   "strategy_orb_enabled"),
            ("BOS_MSS",    "strategy_bos_enabled"),
            ("VWAP_PB",    "strategy_vwap_enabled"),
            ("FVG",        "strategy_fvg_enabled"),
            ("IFVG",       "strategy_ifvg_enabled"),
            ("MID_BRK",    "strategy_mid_enabled"),
            ("AFT_REV",    "strategy_aft_enabled"),
            ("TREND_CONT", "strategy_tcont_enabled"),
            ("CHAN_BREAK",  "strategy_chan_enabled"),
            ("GAP_GO",      "strategy_gapgo_enabled"),
            ("LIQ_SWEEP",   "strategy_liqsweep_enabled"),
            ("V2_ORB_PULLBACK", "strategy_orb_pullback_v2_enabled"),
            ("V2_TREND_CONT", "strategy_trend_cont_v2_enabled"),
        )
        if (sid in _approved_strategy_ids
            and _strat_cfg.get(key, _STRAT_DEFAULTS.get(key, False))
            and (not sid.startswith("V2_") or bool(_strat_cfg.get("paper_trading", True))) )
    }
    # mtf_cache: per-user, per-ticker cache dict (see trading/state.py's
    # "mtf_1h_cache" key + trading/mtf_live_gate.py) — passing both alpaca and
    # this cache is what turns on the Gap 3 MTF confirmation gate; every other
    # route_signals() caller (backtester, audit tools) omits them and is
    # unaffected. Gate itself still defaults OFF via mtf_confirmation_enabled.
    _candidate_observer = None
    _observation_only_strategies: set[str] = set()
    _observation_resolver = None
    if paper and bool(settings.get("shadow_ledger_enabled", True)):
        from shadow_ledger import record_router_candidate, mark_candidate_observed_only
        _candidate_observer = record_router_candidate
        if bool(settings.get("shadow_observe_all_strategies", True)):
            from strategy_router.evaluators import ACTIVE_STRATEGIES
            _observation_only_strategies = {sid for sid, _ in ACTIVE_STRATEGIES} - _enabled
            _observation_resolver = mark_candidate_observed_only
    # The router receives approved strategies for potential entry plus a
    # separate paper-only observation set.  Observed-only signals cannot make
    # it back out of the router, so they cannot reach contract selection.
    _signals = route_signals(df5, ticker, enabled_strategies=_enabled,
                              alpaca=alpaca, mtf_cache=_US.setdefault("mtf_1h_cache", {}),
                              candidate_observer=_candidate_observer,
                              observation_only_strategies=_observation_only_strategies,
                              observation_resolver=_observation_resolver)
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
    strategy_id = _top.strategy_id   # "INST_ORB" | "BOS_MSS" | "VWAP_PB" | "FVG"
    _signal_tier = getattr(_top, "tier", "main")
    _US["last_signal"]     = direction
    _US["last_strategy_id"]= strategy_id

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
    if _loss_ctx:
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
    if ticker.upper() in ("SPY", "QQQ"):
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
    if ticker.upper() not in ("SPY", "QQQ"):
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

    # ── Current price ─────────────────────────────────────────────────────────
    quote = alpaca.get_latest_quote(ticker)
    if not quote:
        return
    current_price = (quote.get("ap", 0) + quote.get("bp", 0)) / 2
    if current_price <= 0:
        return

    # ── Select contract ───────────────────────────────────────────────────────
    opt_type = "call" if direction == "bullish" else "put"
    # Budget cap now SCALES with the account: max_spend = balance × max_position_dollars_pct.
    # max_position_dollars_pct (15) was previously a dead setting — $750 was a
    _cap_pct  = settings.get("max_position_dollars_pct")
    if _cap_pct:
        max_spend = balance * (_cap_pct / 100.0)
    else:
        max_spend = settings.get("max_position_dollars", 750.0)
    # V2's paid TSLA study used a distinct, predeclared contract rule.  Keep
    # Lock the V2 strategy to its reviewed contract definition in *both* paper
    # and a future explicitly-approved live mode.  Today V2 remains disabled
    # and paper-only through its settings gate; this removes a hidden cleanup
    # task rather than enabling an order path.
    _v2_paid_parity = uses_v2_orb_execution_profile(strategy_id)
    if _v2_paid_parity:
        contract, _sel_info = select_v2_orb_contract(
            tradier, ticker, direction, current_price, max_spend,
        )
    else:
        contract, _sel_info = select_contract(tradier, ticker, direction, current_price, max_spend)
    if not contract:
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

    ask_price = contract["ask"]

    # ── Slippage-adjusted entry price ─────────────────────────────────────────
    # All sizing and R:R calculations use the worst-case fill (ask + 5% slippage)
    # so we never enter a trade whose numbers only work at the quoted price.
    eff_entry = _risk.slippage_adjusted_entry(ask_price)

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
        with open(_state_path) as _f:
            _bs = _json.load(_f)
        _bs["last_eval_ticker"]              = ticker
        _bs["last_eval_opt_type"]            = opt_type
        _bs["last_eval_premium"]             = ask_price
        _bs["last_eval_eff_entry"]           = eff_entry
        _bs["last_eval_time"]                = _US["last_eval_time"]
        _bs["last_eval_expiry"]              = _US["last_eval_expiry"]
        _bs["last_eval_strike"]              = _US["last_eval_strike"]
        _bs["last_eval_contract_symbol"]     = _US["last_eval_contract_symbol"]
        _bs["risk_budget_usd"]               = round(balance * _risk.effective_risk_pct(balance), 2)
        _bs["max_affordable_premium"]        = _risk.max_affordable_premium(balance)
        _json.dump(_bs, open(_state_path, "w"))
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
        _bs_c["eval_log"]      = _US["eval_log"]
        _json.dump(_bs_c, open(_state_path, "w"))
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
        _spread_max = float(settings.get("spread_gate_pct", 8)) / 100.0   # was stale 25, fixed 2026-07-22
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
    if not rr_allowed:
        # evaluate_rr() already emitted the Trade_Blocked_Low_RR structured log
        log_event("INFO", "bar_eval",
                  f"🟡 [{ticker}] Skipping this candle — the reward is less than 1.6× the risk "
                  f"at the current price (${eff_entry:.2f}). Waiting for a better entry point.")
        _rr_val = float(rr_audit.get("rr_ratio", 0)) if isinstance(rr_audit, dict) else 0.0
        _skip_log(ticker, "rr_too_low", strategy=strategy_id, confidence=_top.confidence, rr=_rr_val, direction=direction, tier=_signal_tier)
        return

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
            _ds_result = None
            try:
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
                    _ds_trend_1h = get_live_1h_bias(
                        alpaca, ticker, direction, _US.setdefault("mtf_1h_cache", {})
                    )
                    if _ds_trend_1h == "neutral":
                        _ds_trend_1h = None   # no signal either way — keep prior "don't mention it" behavior
                except Exception:
                    _ds_trend_1h = None   # never let this optional context block the review call

                from ai_reasoning.decision_support import review_entry
                _ds_result = review_entry(
                    ticker=ticker, strategy_id=strategy_id, direction=direction,
                    confidence=_top.confidence, rvol=entry_rvol,
                    contract_symbol=contract["symbol"], option_type=opt_type,
                    strike=contract.get("strike"), expiry=contract.get("expiry", ""),
                    n_contracts=n_contracts, entry_price=eff_entry,
                    rr_ratio=rr_audit["R_R_Ratio"], paper=_is_paper_trade,
                    rsi=_ds_rsi, macd_hist=_ds_macd_hist, adx=_ds_adx,
                    ema_aligned=_ds_ema_align, trend_1h_bias=_ds_trend_1h,
                )
            except Exception as _ds_ex:
                # review_entry() already fails open internally — this outer
                # try/except is a second, independent safety net in case the
                # import or the MTF feature computation above raises before
                # review_entry() is even reached. Never let this block a
                # trade the deterministic system already approved.
                logger.warning("AI decision support call failed (non-fatal, trade proceeds): %s", _ds_ex)
                _ds_result = None

            if _ds_result is not None and _ds_result.action == "veto":
                log_event("INFO", "bar_eval",
                          f"🟣 [{ticker}] AI decision support VETO — "
                          f"{_ds_result.rationale or 'no reason given'}")
                _skip_log(ticker, "ai_decision_veto", strategy=strategy_id, confidence=_top.confidence, tier=_signal_tier,
                         direction=direction, detail=_ds_result.rationale or "AI review declined, no rationale given")
                return
            elif _ds_result is not None and _ds_result.action == "reduce_size":
                _ds_resized = int(n_contracts * _ds_result.size_multiplier)
                if _ds_resized < 1:
                    # Floored to 0 contracts — treat as a veto rather than
                    # place a 0-contract order.
                    log_event("INFO", "bar_eval",
                              f"🟣 [{ticker}] AI decision support reduced size to 0 "
                              f"contracts — treating as VETO. {_ds_result.rationale or ''}")
                    _skip_log(ticker, "ai_decision_veto", strategy=strategy_id, confidence=_top.confidence, tier=_signal_tier,
                             direction=direction, detail=f"resized to 0 contracts — {_ds_result.rationale or 'no rationale given'}")
                    return
                elif _ds_resized < n_contracts:
                    log_event("INFO", "bar_eval",
                              f"🟣 [{ticker}] AI decision support reduced size: "
                              f"{n_contracts} → {_ds_resized} contracts. {_ds_result.rationale or ''}")
                    n_contracts = _ds_resized
                    _US["last_eval_contracts"] = n_contracts
                # else: multiplier didn't actually change the integer contract
                # count (e.g. 2c × 0.9 still floors to 2) — nothing to apply.

    # ── Signal-only mode gate ─────────────────────────────────────────────────
    # All quality checks passed. If signal_only_mode is on, broadcast the alert
    # but skip execution — user enters the trade manually in their broker.
    if collection_only:
        log_event("INFO", "trading_logic",
                  f"🔬 [{ticker}] Research record only — maintenance prevents every order and exit.")
        return

    if settings.get("signal_only_mode", False):
        _s1_disp = round(eff_entry * 1.5, 2)
        log_event("INFO", "trading_logic",
                  f"📡 [{ticker}] MANUAL SIGNAL — {opt_type.upper()} "
                  f"${contract.get('strike', '')} exp {contract.get('expiry', '')} "
                  f"| {n_contracts}c @ ${eff_entry:.2f} → ${_s1_disp:.2f} "
                  f"[{strategy_id}] — Signal-Only mode is ON. Enter this trade yourself.")
        return

    # ── Place order ───────────────────────────────────────────────────────────
    # Use the raw ask_price for the actual limit order sent to the broker
    # (eff_entry is our internal worst-case planning price, not the bid we send).
    order = None

    # Always route through the broker — the paper/live destination is controlled
    # by ALPACA_BASE_URL in .env (paper-api.alpaca.markets vs api.alpaca.markets).
    _entry_key = (contract["symbol"], _now_et().strftime("%H:%M"))
    if _US.get("_last_order_key") == _entry_key:
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
    _order_mid, _order_ask = entry_limit_prices(
        ask=ask_price, midpoint=_c_mid, v2_paper_pilot=_v2_paid_parity,
    )
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
    order = alpaca.place_option_order(
        symbol          = contract["symbol"],
        qty             = n_contracts,
        side            = "buy",
        order_type      = "limit",
        limit_price     = _order_mid,
        step_to_price   = _order_ask,
        position_intent = "buy_to_open",
    )

    # FIX S1: Only record trade if order actually filled
    if order is None:
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
        return

    # Use `or ask_price` (not dict.get default) so that a None confirmed_fill_price
    # (returned by paper_assumed_fill path in _wait_for_fill) also falls back to ask.
    confirmed_price = order.get("confirmed_fill_price") or ask_price
    entry_utc       = _now_et()   # tz-aware ET — stored as ET ISO in DB

    # FIX 2026-07-20 (Alpaca fills audit): broker.py's _wait_for_fill now
    # always reports the REAL filled_qty (previously a partial fill either
    # vanished as None or got silently recorded at the full REQUESTED size).
    # Record the position at the size that ACTUALLY filled, not the size we
    # asked for — otherwise the DB shows more contracts open than Alpaca
    # really holds, which throws off risk sizing and P&L on this trade.
    _filled_qty = int(order.get("filled_qty") or n_contracts)
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

    trade_id = insert_trade(
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
        strategy_id     = _US.get("last_strategy_id", "INST_ORB"),
        stop_price      = _stop_px,
        target_price    = _target_px,
        annotations_json= _entry_annotations_json,
        tier            = _signal_tier,
        broker_account_id=settings.get("active_broker_account_id") or None,
    )

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
        _journal_id = _log_journal(ticker, _US.get("last_strategy_id", "INST_ORB"), direction, _top.confidence,
                     outcome="entered", reason_detail=f"R:R={rr_audit['R_R_Ratio']}", trade_id=trade_id,
                     context={
                         "trigger_bar": str(_top.trigger_bar),
                         "strategy_meta": _top.meta,
                         "contract": {
                             "symbol": contract.get("symbol"), "strike": contract.get("strike"),
                             "expiry": contract.get("expiry"), "bid": contract.get("bid"),
                             "ask": contract.get("ask"), "spread": contract.get("spread"),
                             # Present only for the TSLA V2 paper pilot.  This
                             # lets the learner-facing journal distinguish a
                             # paid-study-aligned contract from the normal
                             # generic selector without guessing from price.
                             "selection_model": contract.get("selection_model"),
                             "research_eligibility": _sel_info.get("research_eligibility"),
                         },
                         "rr_ratio": rr_audit.get("R_R_Ratio"),
                     }, tier=_signal_tier)
        if _journal_id is None:
            logger.error(
                "signal_trade_link_missing: trade_id=%s ticker=%s strategy=%s",
                trade_id, ticker, _US.get("last_strategy_id", "INST_ORB"),
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

    # ── Structural stop: convert entry_bar_high/low → option stop price ───────
    # VWAP_PB bearish and CHAN_BREAK bearish signals carry entry_bar_high in meta.
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
            "Strategy_ID":             _US.get("last_strategy_id", "INST_ORB"),
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
            "INST_ORB":  "Opening Range Breakout",
            "VWAP_PB":   "VWAP Pullback",
            "BOS_MSS":   "Break of Structure",
            "FVG":       "Fair Value Gap",
            "CHAN_BREAK": "Channel Rejection",
            "MID_BRK":   "Mid-Day Breakdown",
            "TREND_CONT":"Trend Continuation",
        }.get(_US.get("last_strategy_id", "INST_ORB"), "ORB")
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
            strategy_id      = _US.get("last_strategy_id", "INST_ORB"),
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
