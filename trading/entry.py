"""
trading/entry.py — Ticker/contract selection and the main per-tick evaluation.

Functions:
  select_ticker    — phase-based ticker selection (SPY/QQQ phase 1; expanded phase 2)
  select_contract  — option chain selection with cost/spread/OI filters
  _tick            — full per-tick body (UNTOUCHED — zero logic changes)

NOTE on __file__:
  This module lives in trading/ but _tick() writes bot_state.json and the
  heartbeat file using Path(__file__).parent.  Without the redirect below,
  those files would land in trading/ instead of the project root.
  We override __file__ at import time so Path(__file__).parent always resolves
  to the project root — no code inside _tick() is changed.
"""

from __future__ import annotations

# ── __file__ redirect ─────────────────────────────────────────────────────────
# Must happen BEFORE any Path(__file__) usage anywhere in this module.
import os as _os_file_fix
__file__ = _os_file_fix.path.join(
    _os_file_fix.path.dirname(_os_file_fix.path.dirname(_os_file_fix.path.abspath(__file__))),
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

# ── Project imports ───────────────────────────────────────────────────────────
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
from alerts import send_alert
from tax_engine import record_sweep

# ── State / shared globals (from state.py) ────────────────────────────────────
from trading.state import (
    LIVE_STATE, _now_et, _ET_TZ,
    _DATA_GAP_WARN_MINUTES, _DATA_GAP_PAUSE_MINUTES, _update_data_gap,
)

# ── Sibling job imports ───────────────────────────────────────────────────────
from trading.diagnostics import _log_bar_thinking, _check_ghost_positions, _sweep_orphaned_orders
from trading.position_manager import _manage_open_position, _close_position

logger = logging.getLogger("celo_trader.trading_logic")

# Trade-scoped adapter — reset each time a new position opens.
# _tick() modifies this with `global _trade_log`; position_manager.py reads it
# via deferred `from trading import entry as _em; _em._trade_log`.
_trade_log: logging.Logger = logger

# RiskManager instance — set by loop.py via `import trading.entry as _em; _em._risk = ...`
# _tick() modifies this with `global _risk`.
_risk: Optional[RiskManager] = None


# ── Ticker selection ──────────────────────────────────────────────────────────

def select_ticker(alpaca: AlpacaClient, tradier: TradierClient, balance: float) -> Optional[str]:
    """
    Phase-based ticker selection:
    Phase 1 (<$25k): SPY and QQQ only — tightest spreads, most liquid options
    Phase 2 ($25k+): Expands to top large-cap movers ranked by relative volume
    Also checks trading window before selecting any ticker.
    """
    from config import get_trading_windows as _gtw

    _now_et_time = _now_et()
    _hm          = _now_et_time.hour * 60 + _now_et_time.minute
    _windows = _gtw(balance)
    _in_window = any(
        int(s.split(":")[0]) * 60 + int(s.split(":")[1]) <= _hm <=
        int(e.split(":")[0]) * 60 + int(e.split(":")[1])
        for s, e in _windows
    )
    if not _in_window:
        logger.debug("Trading blocked: Outside trading window")
        return None

    phase2_boundary = float(get_settings().get("phase_2_boundary", 25000.0))

    if balance < phase2_boundary:
        candidates = ["SPY", "QQQ"]
        bar_dict = {}
        for t in candidates:
            bars, err = alpaca.get_bars(t, "5Min", limit=25)
            if not err and bars:
                bar_dict[t] = bars
        ranked = relative_volume_rank(bar_dict) if bar_dict else candidates
        selected = ranked[0] if ranked else candidates[0]
        logger.info("Phase 1 ticker (SPY/QQQ): %s", selected)
        return selected

    else:
        anchor_tickers  = ["SPY", "QQQ"]
        expanded_pool   = ["NVDA", "META", "MSFT", "GOOGL", "AAPL", "AMZN", "TSLA"]
        bar_dict = {}
        for t in anchor_tickers + expanded_pool:
            bars, err = alpaca.get_bars(t, "5Min", limit=25)
            if not err and bars:
                bar_dict[t] = bars

        ranked = relative_volume_rank(bar_dict)
        extra    = [t for t in ranked if t in expanded_pool][:2]
        universe = list(dict.fromkeys(anchor_tickers + extra))
        logger.info("Phase 2 universe: %s", universe)
        return universe[0] if universe else "SPY"


# ── Contract selection ────────────────────────────────────────────────────────

def select_contract(
    tradier: TradierClient,
    ticker: str,
    direction: str,
    current_price: float,
    max_spend: float,
) -> Tuple[Optional[dict], dict]:
    """
    Select the best option contract for entry.

    Contract filters (in order):
      1. First OTM strike (call: above price, put: below price)
      2. ask between MIN_CONTRACT_COST ($0.05) and MAX_CONTRACT_COST ($10.00)
      3. ask × 100 ≤ max_spend (position dollar limit from settings)
      4. bid-ask spread ≤ MAX_BID_ASK_SPREAD ($0.50)
      5. open_interest ≥ MIN_OPEN_INTEREST (100)

    Returns (contract, info) where info["reason"] is one of:
      "selected", "api_error", "no_expirations", "no_chain_data",
      "over_budget", "filtered"
    """
    option_type = "call" if direction == "bullish" else "put"
    info = {"reason": "no_chain_data", "cheapest_cost": None, "cheapest_symbol": None}

    try:
        expirations = tradier.get_expirations(ticker)
    except Exception as ex:
        logger.warning("get_expirations(%s) raised: %s — skipping contract selection", ticker, ex)
        info["reason"] = "api_error"
        return None, info

    if not expirations:
        logger.debug("No expirations returned for %s", ticker)
        info["reason"] = "no_expirations"
        return None, info

    from config import MAX_BID_ASK_SPREAD as _SPREAD_MAX, MIN_OPEN_INTEREST as _MIN_OI

    saw_chain_data = False

    for expiry in expirations:
        try:
            chain = tradier.get_option_chain(ticker, expiry, option_type)
        except Exception as ex:
            logger.debug("get_option_chain(%s %s %s) raised: %s", ticker, expiry, option_type, ex)
            continue
        if not chain:
            continue
        saw_chain_data = True

        if option_type == "call":
            candidates = sorted([c for c in chain if c["strike"] > current_price],
                                 key=lambda x: x["strike"])
        else:
            candidates = sorted([c for c in chain if c["strike"] < current_price],
                                 key=lambda x: x["strike"], reverse=True)

        for contract in candidates:
            ask    = contract.get("ask", 0)
            spread = contract.get("spread", 999)
            oi     = contract.get("open_interest", 0)

            if ask < MIN_CONTRACT_COST:
                logger.debug("Skip %s — ask $%.2f below min $%.2f",
                             contract.get("symbol","?"), ask, MIN_CONTRACT_COST)
                continue
            if ask > MAX_CONTRACT_COST:
                logger.debug("Skip %s — ask $%.2f above max $%.2f",
                             contract.get("symbol","?"), ask, MAX_CONTRACT_COST)
                continue
            cost = ask * 100
            if cost > max_spend:
                logger.debug("Skip %s — cost $%.0f exceeds max_spend $%.0f",
                             contract.get("symbol","?"), cost, max_spend)
                if info["cheapest_cost"] is None or cost < info["cheapest_cost"]:
                    info["cheapest_cost"]   = cost
                    info["cheapest_symbol"] = contract.get("symbol", "?")
                info["reason"] = "over_budget"
                continue
            if spread > _SPREAD_MAX:
                logger.debug("Skip %s — spread $%.2f > max $%.2f",
                             contract.get("symbol","?"), spread, _SPREAD_MAX)
                continue
            if oi < _MIN_OI:
                logger.debug("Skip %s — OI %d < min %d",
                             contract.get("symbol","?"), oi, _MIN_OI)
                continue

            contract["expiry"] = expiry
            logger.info(
                "Contract selected: %s exp=%s strike=%.2f ask=%.2f spread=%.2f OI=%d",
                contract["symbol"], expiry, contract["strike"],
                ask, spread, oi,
            )
            info["reason"] = "selected"
            return contract, info

    if not saw_chain_data:
        info["reason"] = "no_chain_data"
    elif info["cheapest_cost"] is None:
        info["reason"] = "filtered"

    return None, info


# ── Per-tick evaluation ───────────────────────────────────────────────────────

def _tick(alpaca: AlpacaClient, tradier: TradierClient) -> None:
    global _risk

    # ── CRITICAL: ticker and status must be initialized before ANY branch ─────
    # Python treats any variable assigned ANYWHERE in a function as local
    # throughout the entire scope. Without this plain assignment first, every
    # log_event() call before the ticker-selection block raises UnboundLocalError.
    ticker = None                          # overwritten at ticker-selection block
    LIVE_STATE["status"] = "scanning"      # reset here so bot_state.json write
    # below never lags with a stale "standby" value from the previous tick.
    LIVE_STATE["last_update"] = _now_et().isoformat()

    # ── FIX S6: Market hours check ────────────────────────────────────────────
    # Write heartbeat so dashboard can detect the bot is running
    import pathlib as _pl, time as _tm
    _hb = _pl.Path(__file__).parent / ".bot_heartbeat"
    _hb.write_text(str(_tm.time()))

    # Fast local time check BEFORE any Alpaca API call.
    # If we're clearly outside extended hours (8 PM – 4 AM ET), skip the
    # Alpaca is_market_open() call entirely — it's guaranteed False and
    # making the request every 60 s all night generates spurious alpaca_get_failed
    # errors that pollute the Bot Thinking / Network panel.
    _now_local = _now_et()
    _hm_local  = _now_local.hour * 60 + _now_local.minute
    _is_weekend = _now_local.weekday() >= 5   # Saturday=5, Sunday=6
    _extended_hours = 4 * 60 <= _hm_local < 20 * 60  # 4 AM – 8 PM ET
    if _is_weekend or not _extended_hours:
        # Definitely closed — no need to call Alpaca
        market_open = False
        LIVE_STATE["market_open"] = False
    else:
        market_open = alpaca.is_market_open()
        LIVE_STATE["market_open"] = market_open

    # Always write state so dashboard knows bot is alive even when market closed
    import json as _json, time as _time
    _state_path = Path(__file__).resolve().parent / "bot_state.json"

    if not market_open:
        LIVE_STATE["status"] = "market_closed"
        # Reset all session flags at market close so tomorrow starts fresh
        LIVE_STATE["orb_triggered"]    = False
        LIVE_STATE["flip_eligible"]    = False
        LIVE_STATE["flip_direction"]   = None
        LIVE_STATE["flip_ticker"]      = None
        LIVE_STATE["scanner_ran_today"]= False   # allow fresh scan tomorrow
        LIVE_STATE["scan_watchlist"]   = []
        LIVE_STATE["scan_idx"]         = 0
        logger.debug("Market closed — skipping tick, session flags reset")
        try:
            # FIX: "or" instead of dict.get(key, fallback) — the fallback only
            # fires when the key is ABSENT, but LIVE_STATE["account_balance"]
            # is always present (initialized to 0.0 at module load). A stale/
            # zero balance (e.g. before the first market-open tick has ever
            # run) would otherwise be written to bot_state.json verbatim as
            # 0.0 instead of falling back to last_known_balance.
            _mc_balance = (LIVE_STATE.get("account_balance") or
                           get_settings().get("last_known_balance", STARTING_CAPITAL))
            _json.dump({
                "running":                True,
                "account_balance":        _mc_balance,
                # Preserve last-known buying power / ghost-position alert
                # across the market-closed overwrite — same reasoning as
                # current_option_price below.
                "options_buying_power":   LIVE_STATE.get("options_buying_power", 0),
                "ghost_position_alert":   LIVE_STATE.get("ghost_position_alert"),
                "session_pnl":            LIVE_STATE.get("session_pnl", 0),
                "status":                 "market_closed",
                "current_ticker":         None,
                "last_signal":            None,
                "market_open":            False,
                "last_update":            _time.strftime("%H:%M:%S"),
                "entry_time":             None,
                "stage1_done":            False,
                "orb_triggered":          False,
                "current_stop_pct":       _risk.ORB_STOP_PCT if _risk else 0.30,
                "flip_eligible":          False,
                "flip_direction":         None,
                "flip_ticker":            None,
                "last_direction":         LIVE_STATE.get("last_direction"),
                "last_trade_closed_time": LIVE_STATE.get("last_trade_closed_time"),
                # Network health persisted so dashboard shows correct banner at close
                "network_ok":             LIVE_STATE.get("network_ok", True),
                # Risk-sizing info — kept visible after-hours so the user can
                # plan for tomorrow's session without having to ask.
                "risk_budget_usd":        round(_mc_balance * _risk.effective_risk_pct(_mc_balance), 2) if _risk else 0.0,
                "max_affordable_premium": _risk.max_affordable_premium(_mc_balance) if _risk else 0.0,
                "last_eval_ticker":       LIVE_STATE.get("last_eval_ticker"),
                "last_eval_opt_type":     LIVE_STATE.get("last_eval_opt_type"),
                "last_eval_premium":      LIVE_STATE.get("last_eval_premium"),
                "last_eval_eff_entry":    LIVE_STATE.get("last_eval_eff_entry"),
                "last_eval_time":         LIVE_STATE.get("last_eval_time"),
                "last_eval_expiry":       LIVE_STATE.get("last_eval_expiry"),
                "last_eval_strike":       LIVE_STATE.get("last_eval_strike"),
                # Preserve the last live option premium across the
                # market-closed write — this dict is otherwise a full
                # overwrite of bot_state.json and would silently erase it,
                # making the dashboard's "Current"/"Unrealised P&L" for any
                # position held overnight revert to "–".
                "current_option_price":      LIVE_STATE.get("current_option_price"),
                "current_option_price_time": LIVE_STATE.get("current_option_price_time"),
            }, open(_state_path, "w"))
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
        LIVE_STATE["account_balance"] = balance
        LIVE_STATE["network_ok"]      = True
        # FIX: capture Alpaca's options buying power so the dashboard can show
        # it on the Live Trading page and orders that are about to be rejected
        # for "insufficient options buying power" aren't a total surprise.
        # Falls back to whatever was last known if this field is ever absent.
        LIVE_STATE["options_buying_power"] = (
            float(acct.get("options_buying_power", 0)) if acct
            else LIVE_STATE.get("options_buying_power", 0)
        )
    except Exception as e:
        logger.error("Balance fetch failed: %s — using last known balance", e)
        balance = float(get_settings().get("last_known_balance", STARTING_CAPITAL))
        LIVE_STATE["account_balance"] = balance
        LIVE_STATE["network_ok"]      = not _alpaca_circuit_open()

    # ── Reconciliation: catch positions Alpaca holds that the bot doesn't know
    # about (see _check_ghost_positions docstring for the 2026-06-15 incident
    # that motivated this). Stored in LIVE_STATE so the market-closed branch
    # above can also persist the last-known value.
    LIVE_STATE["ghost_position_alert"] = _check_ghost_positions(alpaca)

    # ── Write shared state file so dashboard reads live bot state ─────────────
    from config import get_risk_tier as _grt, DAILY_LOSS_HARD_CAP_PCT as _DLHCP
    _kill_locked, _kill_reason = check_kill_lock()
    try:
        _json.dump({
            "running":                True,
            "account_balance":        LIVE_STATE.get("account_balance", 0),
            "options_buying_power":   LIVE_STATE.get("options_buying_power", 0),
            "ghost_position_alert":   LIVE_STATE.get("ghost_position_alert"),
            "session_pnl":            LIVE_STATE.get("session_pnl", 0),
            "status":                 LIVE_STATE.get("status", "idle"),
            "current_ticker":         LIVE_STATE.get("current_ticker"),
            "last_signal":            LIVE_STATE.get("last_signal"),
            "market_open":            LIVE_STATE.get("market_open", False),
            "last_update":            _time.strftime("%H:%M:%S"),
            # ORB-specific fields — dashboard 45-min countdown & stop display
            "entry_time":             LIVE_STATE.get("entry_time"),
            "stage1_done":            LIVE_STATE.get("stage1_done", False),
            "stage1_be_price":        LIVE_STATE.get("stage1_be_price"),
            "orb_triggered":          LIVE_STATE.get("orb_triggered", False),
            "current_stop_pct":       LIVE_STATE.get("current_stop_pct", _risk.ORB_STOP_PCT if _risk else 0.30),
            # Flip-trade fields
            "flip_eligible":          LIVE_STATE.get("flip_eligible", False),
            "flip_direction":         LIVE_STATE.get("flip_direction"),
            "last_direction":         LIVE_STATE.get("last_direction"),
            "last_trade_closed_time": LIVE_STATE.get("last_trade_closed_time"),
            # Scanner fields — visible in dashboard
            "scan_watchlist":         LIVE_STATE.get("scan_watchlist", []),
            "current_scan_idx":       LIVE_STATE.get("scan_idx", 0),
            # Growth mode / risk tier
            "risk_pct":               _grt(balance),
            "growth_mode":            _grt(balance) > 0.01,
            "daily_loss_hard_cap":    _DLHCP,
            # Kill lock
            "kill_locked":            _kill_locked,
            "kill_lock_reason":       _kill_reason,
            # Network health — False when Alpaca circuit breaker is open
            "network_ok":             LIVE_STATE.get("network_ok", True),
            # Data-gap watchdog — how long (minutes) since the last clean bar fetch.
            # 0 = healthy.  ≥5 = bot was blind; dashboard shows a warning banner.
            "data_gap_minutes":          LIVE_STATE.get("data_gap_minutes", 0),
            "last_successful_bar_fetch": LIVE_STATE.get("last_successful_bar_fetch"),
            # ── Risk-sizing visibility ────────────────────────────────────────
            # risk_budget_usd:        $ the bot will lose if the 30% stop hits
            #                         on 1 contract (balance x effective_risk_pct).
            # max_affordable_premium: highest raw ask price the bot can size to
            #                         >=1 contract right now — SIZING_ZERO fires
            #                         above this. Shown proactively so the user
            #                         never has to ask "why did sizing return 0".
            "risk_budget_usd":        round(balance * _risk.effective_risk_pct(balance), 2) if _risk else 0.0,
            "max_affordable_premium": _risk.max_affordable_premium(balance) if _risk else 0.0,
            # Most recently evaluated contract (set when the bot looks at a
            # specific option to size/enter — persists until the next evaluation).
            "last_eval_ticker":       LIVE_STATE.get("last_eval_ticker"),
            "last_eval_opt_type":     LIVE_STATE.get("last_eval_opt_type"),
            "last_eval_premium":      LIVE_STATE.get("last_eval_premium"),
            "last_eval_eff_entry":    LIVE_STATE.get("last_eval_eff_entry"),
            "last_eval_time":         LIVE_STATE.get("last_eval_time"),
            "last_eval_expiry":       LIVE_STATE.get("last_eval_expiry"),
            "last_eval_strike":       LIVE_STATE.get("last_eval_strike"),
        }, open(_state_path, "w"))
    except Exception:
        pass

    # ── Manage existing position(s) ────────────────────────────────────────────
    # NEW (MAX_CONCURRENT_POSITIONS): manage ALL open trades (up to the limit),
    # not just a single one. The orphaned-order sweep runs first so any resting
    # order left behind by a failed/partial fill from a prior tick can never
    # silently fill later as an unsupervised ghost position.
    # ── 3:55 PM ET hard session cutoff ───────────────────────────────────────
    # At or after 3:55 PM ET: cancel all pending orders and market-close all
    # open positions, then return.  This prevents holding through the final
    # auction where bid/ask spreads blow out and fills become unpredictable.
    # SESSION_HARD_CUTOFF_HM = (15, 55) from config.
    _et_now_cut = _now_et()
    _cutoff_minutes = SESSION_HARD_CUTOFF_HM[0] * 60 + SESSION_HARD_CUTOFF_HM[1]
    _now_minutes    = _et_now_cut.hour * 60 + _et_now_cut.minute
    if _now_minutes >= _cutoff_minutes:
        try:
            # Cancel any pending/working orders first to avoid orphaned fills
            _pending = alpaca.get_open_orders() or []
            for _ord in _pending:
                try:
                    alpaca.cancel_order(_ord.get("id", ""))
                    logger.info("session_cutoff_cancel_order id=%s", _ord.get("id"))
                except Exception as _ce:
                    logger.warning("Cutoff: failed to cancel order %s: %s", _ord.get("id"), _ce)

            # Force-close all bot-managed open positions
            _cutoff_trades = get_open_trades()
            for _ct in _cutoff_trades:
                if _ct.get("strategy_id") == "RECOVERED_UNTRACKED":
                    continue
                try:
                    _cq = tradier.get_option_quote(_ct.get("contract_symbol", ""))
                    _cx = _cq.get("mid", _ct.get("entry_price", 0)) if _cq else _ct.get("entry_price", 0)
                    _close_position(alpaca, _ct, _cx, "session_hard_cutoff_355pm")
                    log_event("WARNING", "trading_logic",
                              f"🔴 [{_ct.get('ticker')}] 3:55 PM hard cutoff — "
                              f"force-closing position to avoid after-hours exposure.")
                except Exception as _ex:
                    logger.error("Cutoff: failed to close trade %s: %s", _ct.get("id"), _ex)
        except Exception as _cut_ex:
            logger.error("Session cutoff sweep failed: %s", _cut_ex)

        LIVE_STATE["status"] = "session_cutoff"
        return   # no new entries after 3:55 PM

    open_trades = get_open_trades()
    LIVE_STATE["open_trades"] = open_trades

    # ── Exclude RECOVERED_UNTRACKED legacy positions from active management ──
    # FIX 2026-06-15: the 7 positions recovered from the ghost-position
    # reconciliation (strategy_id == "RECOVERED_UNTRACKED") were inserted with
    # entry_time = the moment they were recovered, NOT their real entry time.
    # If _manage_open_position() ran on them, the 45-min time-box / dynamic
    # stop tightening would start counting from that recovery moment and
    # could force-close a legacy position at an arbitrary point unrelated to
    # the ORB strategy that (might have) opened it. Worse, with all 7 counted
    # against MAX_CONCURRENT_POSITIONS=2, the entry gate below would NEVER
    # free up — the bot would be permanently blocked from new trades "for the
    # day" (and every day after) until a human manually closed 6 of them.
    #
    # These legacy positions are still visible (with a per-row "Close
    # Position" button) on the Trade Journal page — they're just excluded
    # from the bot's own automated management/gating, which only applies to
    # positions THIS bot opened.
    _bot_trades = [t for t in open_trades if t.get("strategy_id") != "RECOVERED_UNTRACKED"]
    LIVE_STATE["open_trade"] = _bot_trades[0] if _bot_trades else None

    _sweep_orphaned_orders(alpaca, _bot_trades)

    for _open_trade in _bot_trades:
        _manage_open_position(alpaca, tradier, _open_trade, balance)

    # ── Price-only update for RECOVERED_UNTRACKED trades ─────────────────────
    # These trades are excluded from _manage_open_position (so automated
    # stop/time-box/stage1 logic never fires on them), but the dashboard's
    # Trade Journal needs a live current_option_price to show unrealised P&L.
    # Fetch a Tradier quote for each one and write ONLY the price into
    # bot_state.json["open_positions"] — no management actions taken.
    import json as _json_rec
    _state_path_rec = __import__("pathlib").Path(__file__).resolve().parent / "bot_state.json"
    _recovered_trades = [t for t in open_trades if t.get("strategy_id") == "RECOVERED_UNTRACKED"]
    if _recovered_trades:
        try:
            _rec_state = {}
            if _state_path_rec.exists():
                with open(_state_path_rec) as _f:
                    _rec_state = _json_rec.load(_f)
            _rec_positions = _rec_state.get("open_positions") or {}
            for _rt in _recovered_trades:
                try:
                    _rq = tradier.get_option_quote(_rt["contract_symbol"])
                    if _rq and _rq.get("mid", 0) > 0:
                        _rt_id = str(_rt["id"])
                        _existing_entry = _rec_positions.get(_rt_id) or {}
                        _existing_entry.update({
                            "trade_id":                  _rt["id"],
                            "contract_symbol":           _rt["contract_symbol"],
                            "ticker":                    _rt["ticker"],
                            "option_type":               _rt["option_type"],
                            "entry_price":               _rt["entry_price"],
                            "contracts":                 _rt["contracts"],
                            "current_option_price":      _rq["mid"],
                            "current_option_price_time": _now_et().strftime("%H:%M:%S"),
                        })
                        _rec_positions[_rt_id] = _existing_entry
                except Exception:
                    pass
            _rec_state["open_positions"] = _rec_positions
            with open(_state_path_rec, "w") as _f:
                _json_rec.dump(_rec_state, _f)
        except Exception:
            pass

    if len(_bot_trades) >= MAX_CONCURRENT_POSITIONS:
        # All position slots are full — nothing left to do this tick except
        # manage the existing position(s) above.
        LIVE_STATE["status"] = "in_trade"
        return

    # ── Pre-trade gate ─────────────────────────────────────────────────────────
    # NEW (MAX_CONCURRENT_POSITIONS): if a slot is free but the bot is still
    # holding a position in the OTHER slot, reflect "in_trade" for the
    # dashboard — but don't return; fall through to evaluate a new entry for
    # the free slot below.
    LIVE_STATE["status"] = "in_trade" if _bot_trades else "scanning"
    settings = get_settings()
    allowed, reason = _risk.can_trade(balance, has_open_position=False)
    if not allowed:
        logger.debug("Trading blocked: %s", reason)
        if "limit" in reason.lower() or "kill" in reason.lower():
            LIVE_STATE["status"] = "halted"
        elif "window" in reason.lower():
            # Show a specific standby state so the UI doesn't claim "idle" while
            # the bot is actually alive and waiting for the next session window.
            LIVE_STATE["status"] = "standby"
        else:
            LIVE_STATE["status"] = "idle"
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
    # signal so all 5 top movers are checked before any is re-scanned.
    # Strip blacklisted tickers (leveraged/inverse ETFs) from any cached watchlist.
    # The scanner already filters these, but a stale LIVE_STATE from a pre-fix
    # session may still contain SQQQ/TQQQ — remove them here as a hard guard.
    from scanner import TICKER_BLACKLIST as _BL
    watchlist = [t for t in (LIVE_STATE.get("scan_watchlist") or []) if t not in _BL]
    if not watchlist:
        # Watchlist empty: run an on-demand scan (missed pre-market, or first boot)
        try:
            watchlist = run_scan(alpaca, max_tickers=10)
        except Exception:
            watchlist = get_watchlist()  # read from disk; falls back to SPY/QQQ
        if not watchlist:
            watchlist = ["SPY", "QQQ"]
        LIVE_STATE["scan_watchlist"]    = watchlist
        LIVE_STATE["scan_idx"]          = 0
        LIVE_STATE["scanner_ran_today"] = True
        logger.info("on_demand_scan_done", extra={
            "event": "on_demand_scan_done", "watchlist": watchlist,
        })

    # Advance to next ticker in round-robin
    idx    = LIVE_STATE.get("scan_idx", 0) % len(watchlist)
    ticker = watchlist[idx]
    LIVE_STATE["scan_idx"]         = (idx + 1) % len(watchlist)
    LIVE_STATE["current_ticker"]   = ticker
    logger.debug("Scanning ticker %s (%d/%d)", ticker, idx + 1, len(watchlist))

    # FIX 2026-06-22 (direct request): the per-ticker session-long loss
    # cooldown ("Fix 1") that used to gate here is removed — see the matching
    # comment where trades close, a few thousand lines down, for the
    # rationale and the known risk being accepted.

    # ── Fix 2 (new): Same-ticker concurrent position guard ───────────────────
    # MAX_CONCURRENT_POSITIONS=2 is for DIVERSIFICATION — two different stocks,
    # not two legs on the same stock.  Without this guard, both slots can open
    # the same ticker simultaneously (SPY+SPY, NVDA+NVDA), doubling exposure
    # to a losing trade.  Confirmed from 2026-06-18 audit: SPY 111+112 cost
    # -$63 combined; NVDA 115+116 cost -$23 combined.
    _open_tickers = {t.get("ticker", "") for t in LIVE_STATE.get("open_trades", [])}
    if ticker in _open_tickers:
        log_event("INFO", "bar_eval",
                  f"🔷 [{ticker}] Skipping — already holding an open position on this ticker. "
                  f"Bot won't open a second concurrent position on the same stock.")
        return

    # ── Fix 3 (new): Post-win cooling period ─────────────────────────────────
    # After a profitable close, block the same ticker for WIN_COOLDOWN_MINUTES
    # (10 min).  This prevents the pattern of winning on AAPL then immediately
    # chasing back in 12 seconds later and giving the win back — confirmed as
    # AAPL 103→105 (+$22 → -$45) and SPY 110→111 (+$41 → -$42) on 2026-06-18.
    _WIN_COOLDOWN_MINUTES = 10
    _win_cooldowns = LIVE_STATE.get("ticker_win_cooldown") or {}
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
                del LIVE_STATE["ticker_win_cooldown"][ticker]
            except (KeyError, TypeError):
                pass

    # ── Re-entry gate ─────────────────────────────────────────────────────────
    # Bot may re-enter the same ticker after cooldowns expire.  Quality gates:
    #   • loss cooldown (Fix 1): blocks re-entry after any losing trade
    #   • concurrent ticker guard (Fix 2): no doubling down on same stock
    #   • win cooldown (Fix 3): 10-min wait after a profitable exit
    #   • RVOL floor (≥1.0× absolute minimum, set in strategy_router)
    #   • SPY VWAP macro gate: wrong-way entries flipped/blocked
    #   • Signal confidence and R:R gate must pass on every entry
    # See re-entry quality analysis (2026-06-18 audit) for improvement context.

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
    # occur rather than up to 4 minutes late.  RVOL and vol_sma windows in
    # strategy_router.py are calibrated for 1-min bars (100-bar SMA = ~100 min
    # of intraday context, matching the old 20-bar × 5-min = 100-min window).
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
    LIVE_STATE["last_successful_bar_fetch"] = _now_fetch.isoformat()
    LIVE_STATE["data_gap_minutes"]          = 0

    LIVE_STATE["bars_5m"] = bars_5m   # key name kept for compatibility
    df5 = bars_to_df(bars_5m)

    # ── Augment with historical 5-min bars for cross-day RVOL baseline ───────
    # Alpaca's free IEX tier caps 1Min historical pulls at ~400 bars (today
    # only).  Requesting 7800 1Min bars would either 403 or silently return
    # far fewer bars, breaking RVOL.  Instead we pull 5Min bars (~15 days of
    # history = 1500 bars × 5 min each) — the free tier supports these — and
    # prepend them strictly for RVOL context.  Strategy signals are evaluated
    # on today's 1Min bars alone (df5 is sliced back below).
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
                # done on the 1Min slice passed as the first positional arg.
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
    _enabled: set[str] = {
        sid for sid, key in (
            ("INST_ORB",   "strategy_orb_enabled"),
            ("BOS_MSS",    "strategy_bos_enabled"),
            ("VWAP_PB",    "strategy_vwap_enabled"),
            ("FVG",        "strategy_fvg_enabled"),
            ("MID_BRK",    "strategy_mid_enabled"),
            ("AFT_REV",    "strategy_aft_enabled"),
            ("TREND_CONT", "strategy_tcont_enabled"),
            ("CHAN_BREAK",  "strategy_chan_enabled"),
        )
        if _strat_cfg.get(key, True)
    }
    _signals = route_signals(df5, ticker, enabled_strategies=_enabled or None)
    if not _signals:
        LIVE_STATE["last_signal"] = None
        # Log WHY no signal — the bar_eval entry already covers the ORB gate
        # reasoning; this adds a higher-level "no strategy qualified" note so
        # the audit log always shows something on every tick.
        try:
            _last_bar_t = str(df5["time"].iloc[-1]) if not df5.empty else "?"
            log_event("INFO", "bar_eval",
                      f"🟡 [{ticker}] {_last_bar_t[11:16]} — No trade setup found on this candle. "
                      f"Conditions not yet aligned — continuing to watch.")
        except Exception:
            pass
        return

    _top: _RouterSignal = _signals[0]
    direction   = _top.direction      # "bullish" | "bearish"
    entry_rvol  = _top.rvol           # Entry_Volume_Multiplier for audit log
    strategy_id = _top.strategy_id   # "INST_ORB" | "BOS_MSS" | "VWAP_PB" | "FVG"
    LIVE_STATE["last_signal"]     = direction
    LIVE_STATE["last_strategy_id"]= strategy_id

    # ── Flip-direction enforcement ────────────────────────────────────────────
    # When flip_eligible, we prefer the OPPOSITE direction of the stopped trade
    # but we do NOT hard-block a valid signal — market structure always wins.
    #
    # Why: a stale flip token (e.g. "bullish" required from yesterday's stop)
    # would block a perfectly valid ORB SHORT on a bearish open.  We log the
    # mismatch and proceed rather than killing the entry.
    if LIVE_STATE.get("flip_eligible"):
        required_flip = LIVE_STATE.get("flip_direction")
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
            LIVE_STATE["flip_eligible"]  = False
            LIVE_STATE["flip_direction"] = None
            LIVE_STATE["flip_ticker"]    = None
        else:
            logger.info(
                "flip_signal_confirmed",
                extra={
                    "event":          "flip_signal_confirmed",
                    "ticker":         ticker,
                    "flip_direction": direction,
                    "prev_direction": LIVE_STATE.get("last_direction"),
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
            "is_flip":     bool(LIVE_STATE.get("flip_eligible")),
            "status":      "PENDING_RR_GATE",
        },
    )

    # ── SPY VWAP direction gate ───────────────────────────────────────────────
    # Before entering a CALL, confirm SPY is trading ABOVE its intraday VWAP.
    # If SPY is below VWAP the broad market is in a bearish posture; bullish
    # options setups on individual names face strong macro headwinds and fail
    # at a much higher rate.  PUT entries are allowed regardless of VWAP.
    # EXCEPTION: flip trades pass through (they're directional reversals, and
    # blocking a bearish flip on a bullish-VWAP day still makes sense, but a
    # bullish flip when SPY < VWAP should be blocked — so the filter applies
    # to ALL bullish entries including flips).
    # ── SPY macro VWAP check — flip direction rather than block ──────────────
    # If the signal is bullish but SPY is trading BELOW its intraday VWAP,
    # the broad market is in a bearish posture.  Rather than sitting on our
    # hands, we flip the trade to a PUT — the macro tailwind is bearish and
    # we should align with it.  Symmetric: if signal is bearish but SPY is
    # ABOVE VWAP (bullish macro), flip to CALL.
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

        # ── Apply direction flip based on SPY VWAP ───────────────────────────
        if _spy_vwap > 0:
            if direction == "bullish" and _spy_close < _spy_vwap:
                log_event("INFO", "bar_eval",
                          f"🔄 [{ticker}] CALL → PUT flip — SPY (${_spy_close:.2f}) "
                          f"is BELOW VWAP (${_spy_vwap:.2f}). "
                          f"Macro is bearish; aligning signal direction to PUT.")
                direction = "bearish"
            elif direction == "bearish" and _spy_close > _spy_vwap:
                log_event("INFO", "bar_eval",
                          f"🔄 [{ticker}] PUT → CALL flip — SPY (${_spy_close:.2f}) "
                          f"is ABOVE VWAP (${_spy_vwap:.2f}). "
                          f"Macro is bullish; aligning signal direction to CALL.")
                direction = "bullish"
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
    # one-time snapshot of 15% of a $5,000 balance, hardcoded as a flat dollar
    # figure. Recomputing it live each tick means the cap grows with the
    # account instead of becoming an ever-shrinking % of equity over time.
    # Falls back to the old flat "max_position_dollars" only if the % setting
    # is missing entirely.
    _cap_pct  = settings.get("max_position_dollars_pct")
    if _cap_pct:
        max_spend = balance * (_cap_pct / 100.0)
    else:
        max_spend = settings.get("max_position_dollars", 750.0)
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
        elif _reason in ("api_error", "no_expirations", "no_chain_data"):
            # Tradier didn't return usable options data — NOT a budget issue.
            log_event("INFO", "bar_eval",
                      f"🔴 [{ticker}] Couldn't load {opt_type.upper()} option prices from "
                      f"Tradier (no data returned). Skipping this setup — will check again "
                      f"next candle.")
        else:
            # "filtered" — chain data existed but spread/open-interest filters
            # rejected every candidate (not a budget issue).
            log_event("INFO", "bar_eval",
                      f"🔴 [{ticker}] No {opt_type.upper()} contracts met liquidity/spread "
                      f"requirements. Skipping this setup — will check again next candle.")
        return

    ask_price = contract["ask"]

    # ── Slippage-adjusted entry price ─────────────────────────────────────────
    # All sizing and R:R calculations use the worst-case fill (ask + 5% slippage)
    # so we never enter a trade whose numbers only work at the quoted price.
    eff_entry = _risk.slippage_adjusted_entry(ask_price)

    # ── Record what the bot is currently looking at, for the dashboard ───────
    # Surfaces the live contract premium + affordability ceiling proactively
    # (without the user having to ask) by writing them into LIVE_STATE and
    # patching bot_state.json immediately, instead of waiting for next tick.
    LIVE_STATE["last_eval_ticker"]           = ticker
    LIVE_STATE["last_eval_opt_type"]         = opt_type
    LIVE_STATE["last_eval_premium"]          = ask_price
    LIVE_STATE["last_eval_eff_entry"]        = eff_entry
    LIVE_STATE["last_eval_time"]             = _time.strftime("%H:%M:%S")
    LIVE_STATE["last_eval_expiry"]           = contract.get("expiry")
    LIVE_STATE["last_eval_strike"]           = contract.get("strike")
    LIVE_STATE["last_eval_contract_symbol"]  = contract.get("symbol")
    try:
        with open(_state_path) as _f:
            _bs = _json.load(_f)
        _bs["last_eval_ticker"]              = ticker
        _bs["last_eval_opt_type"]            = opt_type
        _bs["last_eval_premium"]             = ask_price
        _bs["last_eval_eff_entry"]           = eff_entry
        _bs["last_eval_time"]                = LIVE_STATE["last_eval_time"]
        _bs["last_eval_expiry"]              = LIVE_STATE["last_eval_expiry"]
        _bs["last_eval_strike"]              = LIVE_STATE["last_eval_strike"]
        _bs["last_eval_contract_symbol"]     = LIVE_STATE["last_eval_contract_symbol"]
        _bs["risk_budget_usd"]               = round(balance * _risk.effective_risk_pct(balance), 2)
        _bs["max_affordable_premium"]        = _risk.max_affordable_premium(balance)
        _json.dump(_bs, open(_state_path, "w"))
    except Exception:
        pass   # non-critical — next full tick write will catch up regardless

    # ── ORB 1% risk sizing (uses slippage-adjusted price) ─────────────────────
    n_contracts = _risk.calculate_contracts(eff_entry, balance)
    if n_contracts < 1:
        logger.warning(
            "ORB sizing returned 0 contracts",
            extra={"event": "sizing_zero", "ask": ask_price, "eff_entry": eff_entry, "balance": balance},
        )
        # Spell out the RISK vs PRICE distinction so this isn't confused with the
        # max_position_dollars / "over_budget" cost cap above. SIZING_ZERO fires
        # when the dollar amount you'd LOSE if the 30% stop hits exceeds your
        # risk_per_trade budget — even if the contract's premium itself is
        # comfortably affordable.
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
        return

    # ── Total-position-cost cap ───────────────────────────────────────────────
    # calculate_contracts() sizes purely off risk_per_trade % and can ask for
    # MORE contracts than max_spend allows on cheap-premium setups —
    # select_contract() only validated that a SINGLE contract fits the budget.
    # Clamp here so total spend (n_contracts × ask × 100) never exceeds max_spend.
    # ask_price > 0 is guaranteed (select_contract enforces MIN_CONTRACT_COST),
    # and select_contract already proved 1 contract fits within max_spend, so
    # _max_affordable is always >= 1.
    _max_affordable = max(1, int(max_spend // (ask_price * 100)))
    if n_contracts > _max_affordable:
        logger.debug(
            "Sizing clamp for %s: risk model wanted %d contracts ($%.0f total), "
            "budget cap ($%.0f) allows %d",
            ticker, n_contracts, n_contracts * ask_price * 100,
            max_spend, _max_affordable,
        )
        n_contracts = _max_affordable

    # ── Spread gate: skip if bid-ask spread > 10% of mid price ───────────────
    # Wide spreads mean we pay an immediate 5–10% toll just getting in and out.
    # On a small account that single spread can wipe a whole risk-budget unit.
    # select_contract() already gates on MAX_BID_ASK_SPREAD ($0.50 absolute),
    # but a $0.50 spread on a $1.00 contract is 50% — devastating.  This
    # percentage check catches cheap contracts with wide relative spreads.
    _c_bid = float(contract.get("bid", 0) or 0)
    _c_ask = float(contract.get("ask", 0) or ask_price)
    _c_mid = (_c_bid + _c_ask) / 2 if _c_bid > 0 else _c_ask
    if _c_mid > 0:
        _spread_pct = (_c_ask - _c_bid) / _c_mid
        if _spread_pct > 0.10:   # 10% max relative spread
            log_event("INFO", "bar_eval",
                      f"🟡 [{ticker}] Skipping — bid-ask spread is "
                      f"{_spread_pct*100:.1f}% of mid price "
                      f"(bid=${_c_bid:.2f} ask=${_c_ask:.2f}). "
                      f"Too wide; waiting for tighter liquidity.")
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

    # ── Place order ───────────────────────────────────────────────────────────
    # Use the raw ask_price for the actual limit order sent to the broker
    # (eff_entry is our internal worst-case planning price, not the bid we send).
    paper = settings.get("paper_trading", True)
    order = None

    # Always route through the broker — the paper/live destination is controlled
    # by ALPACA_BASE_URL in .env (paper-api.alpaca.markets vs api.alpaca.markets).
    # The `paper` flag only tags logs and selects which DB file to write to;
    # it must NOT skip the broker call, otherwise trades never appear in the
    # Alpaca paper account.
    # Fix 3: duplicate-order guard — prevent placing the same order twice in
    # the same minute.  Before this fix every signal generated 2 identical BUY
    # log lines at the same second because both the plain-text handler and the
    # JSON handler emitted the event, and the entry code was called twice per
    # tick (once from each logger path).  Checking the (contract, HH:MM) key
    # is a cheap idempotency guard that blocks the second placement without
    # requiring a lock.
    _entry_key = (contract["symbol"], _now_et().strftime("%H:%M"))
    if LIVE_STATE.get("_last_order_key") == _entry_key:
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
    LIVE_STATE["_last_order_key"] = _entry_key
    # Use ask + 2% as limit price so minor market ticks don't kill the fill.
    # The eff_entry already includes 5% slippage for sizing/R:R — this 2% pad
    # is strictly for order placement and doesn't affect risk calculations.
    _order_limit = round(ask_price * 1.02, 2)
    order = alpaca.place_option_order(
        symbol      = contract["symbol"],
        qty         = n_contracts,
        side        = "buy",
        order_type  = "limit",
        limit_price = _order_limit,
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

    # ── Record to database ────────────────────────────────────────────────────
    # Compute stop/target at entry — stored so the chart can show the position overlay
    _stop_px   = round(_risk.dynamic_stop_price(confirmed_price, entry_utc), 4)
    _target_px = round(_risk.stage1_exit_price(confirmed_price), 4)

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
        strategy_id     = LIVE_STATE.get("last_strategy_id", "INST_ORB"),
        stop_price      = _stop_px,
        target_price    = _target_px,
    )

    # Re-run R:R audit with real trade_id — final structured log record
    _risk.evaluate_rr(
        entry_price              = confirmed_price,
        trade_id                 = trade_id,
        n_contracts              = n_contracts,
        entry_volume_multiplier  = entry_rvol,
    )

    # NEW (MAX_CONCURRENT_POSITIONS): re-read ALL open trades from the DB so
    # open_trades/open_trade reflect this new position alongside any other
    # already-open position.
    LIVE_STATE["open_trades"]      = get_open_trades()
    LIVE_STATE["open_trade"]       = LIVE_STATE["open_trades"][0] if LIVE_STATE["open_trades"] else None
    LIVE_STATE["status"]           = "in_trade"
    LIVE_STATE["orb_triggered"]    = True   # blocks further entries unless flip armed
    LIVE_STATE["last_direction"]   = direction
    # Consume the flip token — after entering the flip trade, no more re-entries
    LIVE_STATE["flip_eligible"]    = False
    LIVE_STATE["flip_direction"]   = None
    LIVE_STATE["flip_ticker"]      = None
    # Fix 2: mark this ticker as having had an ORB entry this session so the
    # bot won't re-enter the same ORB breakout after the trade closes.
    LIVE_STATE.setdefault("orb_entered_today", set()).add(ticker)

    # ── Per-position live-management state (NEW — MAX_CONCURRENT_POSITIONS) ──
    # Each open trade gets its OWN peak/stage/stop tracking so a 2nd concurrent
    # position's stage/stop progress can never overwrite the 1st's (and vice
    # versa). _manage_open_position() reads/writes this dict keyed by trade_id.
    LIVE_STATE["positions"][trade_id] = {
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
    # _manage_open_position can enforce it each tick without another API call.
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
    LIVE_STATE["positions"][trade_id]["struct_stop_price"] = _struct_stop_opt

    persist_peak_price(trade_id, confirmed_price)

    # Bind trade context so all subsequent log lines include trade metadata
    global _trade_log
    try:
        from logger_config import get_trade_logger
        _trade_log = get_trade_logger(
            ticker=ticker,
            contract_symbol=contract["symbol"],
            session_id=str(trade_id),
        )
    except Exception:
        _trade_log = logger

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
            "Strategy_ID":             LIVE_STATE.get("last_strategy_id", "INST_ORB"),
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
        }.get(LIVE_STATE.get("last_strategy_id", "INST_ORB"), "ORB")
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
