"""
trading_logic.py — Main trading loop.

Fixes applied (audit round 1):
  S1  - Fill confirmation: only record trade after broker confirms fill
  S6  - Market hours check at top of every tick — skips weekends/holidays
  S3  - get_bars now returns (bars, is_error); TF errors block signal
  M6  - Position sizing calculated once with real ask price (no double-calc)
  M8  - Ticker selection uses relative_volume_rank for penny tickers (not first-valid)
  M11 - Earnings check applied to ALL tickers (penny AND large-cap)
  M12 - Manual close fetches live quote for exit price (not entry * 0.95)
  S4  - Peak price recovered from DB on restart via risk.recover_peak_price
  M10 - VOLUME_FILTER_MULTIPLIER flows through config → signals
"""

import logging
import time
import threading
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Tuple

import pandas as pd
import pytz as _pytz

# ── Timezone helper ───────────────────────────────────────────────────────────
_ET_TZ = _pytz.timezone("US/Eastern")


def _now_et() -> datetime:
    """
    Return the current wall-clock time as a tz-aware US/Eastern datetime.

    Replaces all datetime.utcnow() calls in this module so that:
      • Timestamps stored in bot_state.json are in market-local time.
      • Trade entry/exit times passed to database.py carry ET timezone info.
      • Trading-window arithmetic uses consistent ET wall-clock time.
    """
    return datetime.now(_ET_TZ)


# Network health watchdog constants
_DATA_GAP_WARN_MINUTES  = 5    # alert after this many minutes without a clean bar fetch
_DATA_GAP_PAUSE_MINUTES = 10   # skip strategy evaluation after this many minutes (stale data)


def _update_data_gap() -> None:
    """
    Called on every FAILED bar fetch.  Updates data_gap_minutes and emits a
    one-time warning the first time the gap crosses _DATA_GAP_WARN_MINUTES.
    The tick returns early before calling this (so strategy evaluation never
    runs on stale/missing data), but we still need to track how long we've
    been blind so the dashboard can show a banner.
    """
    last_str = LIVE_STATE.get("last_successful_bar_fetch")
    if last_str is None:
        # No successful fetch yet this session — treat session start as baseline
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

    # Emit a warning once when crossing the alert threshold
    if gap >= _DATA_GAP_WARN_MINUTES and prev_gap < _DATA_GAP_WARN_MINUTES:
        log_event("WARNING", "network_watchdog",
                  f"⚠️ No bar data received for {gap} minutes — bot is BLIND. "
                  f"Last clean fetch: {last_str[11:16]} ET. "
                  f"Check your internet connection or Alpaca's status page. "
                  f"Strategy evaluation is paused until data resumes.")
        logger.warning("Data gap watchdog: %d minutes without a clean bar fetch", gap)

from config import (
    TRADIER_ACCOUNT_ID,
    LIQUID_TICKERS,
    STARTING_CAPITAL,
    MIN_CONTRACT_COST, MAX_CONTRACT_COST,
    EARNINGS_BLACKOUT_DAYS,
    get_settings, get_risk_tier,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT as _GMT_TL, MID_TIER_RISK_PCT as _MTT_TL,
    MAX_CONCURRENT_POSITIONS,
    SESSION_HARD_CUTOFF_HM,  # (15, 55) — hard close all positions at 3:55 PM ET
    STAGE2_TRAIL_PCT,         # 0.15 — stage 2 trail floor at entry × 1.15
)
from broker import AlpacaClient, TradierClient, get_clients
from signals import (
    bars_to_df, relative_volume_rank, is_near_earnings,
    detect_orb_breakout,   # kept for flip-trade reuse; primary path uses router
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

logger = logging.getLogger("celo_trader.trading_logic")

# Trade-scoped adapter — reset each time a new position opens
_trade_log: logging.Logger = logger   # replaced by TradeContext during active trade

# ── Shared state ──────────────────────────────────────────────────────────────

LIVE_STATE: dict = {
    "account_balance":      0.0,
    "options_buying_power": 0.0,
    "ghost_position_alert": None,
    "open_trade":      None,   # backward-compat: most-recently-opened of open_trades, or None
    "open_trades":     [],     # NEW (MAX_CONCURRENT_POSITIONS support): list of ALL open trade dicts
    # NEW: per-position live-management state, keyed by trade_id. Replaces the
    # single-position fields below (peak_price, stage1_done, stage1_be_price,
    # current_stop_pct, struct_stop_price, current_option_price, etc.) which
    # used to be overwritten in place — that's unsafe once 2 trades can be
    # open at once, since each position needs its OWN stage/peak/stop state.
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
    "scan_watchlist":    [],     # top-5 tickers from last scan (populated at pre-market)
    "scan_idx":          0,      # index into scan_watchlist; cycles each tick
    "scanner_ran_today": False,  # True once pre-market scan completed for this session
    # ── ORB-specific state ────────────────────────────────────────────────────
    "entry_time":            None,   # UTC ISO string — drives the 45-min time-box
    "stage1_done":           False,  # True once 50% tranche has been sold
    "stage1_be_price":       None,   # break-even price for second tranche
    "orb_triggered":         False,  # True once ORB fired today (cleared at midnight)
    # FIX 2026-06-22: was a stale hardcoded 0.30 (the old 30% stop, before
    # task #227 tightened ORB_STOP_PCT to 20%) — drifted out of sync the same
    # way the journal-note text did. RiskManager.ORB_STOP_PCT is the live
    # value; this is only ever the placeholder shown before the first real
    # tick computes the actual dynamic stop.
    "current_stop_pct":      RiskManager.ORB_STOP_PCT,   # live dynamic stop % — tightens each tick
    "struct_stop_price":     None,   # entry_bar_high-derived option stop (VWAP_PB / CHAN_BREAK)
    # ── Flip-trade state ─────────────────────────────────────────────────────
    # Armed when the bot takes a hard stop-loss (dynamic_stop_Xpct).
    # Allows exactly ONE opposite-direction re-entry with full RVOL + R:R gates.
    "flip_eligible":         False,  # True = bot may take a flip trade this session
    "flip_direction":        None,   # "bullish" or "bearish" required for flip entry
    "flip_ticker":           None,   # which ticker armed the flip (per-ticker scoping)
    "last_direction":        None,   # direction of the most recently closed trade
    "last_trade_closed_time": None,  # ISO UTC of last full close (for audit logs)
    # ── Per-session entry guards (Fix 2) ─────────────────────────────────────
    # FIX 2026-06-22: the old "Fix 1" per-ticker session-long loss cooldown
    # (and its ticker_loss_cooldown set) was removed per direct request — the
    # user wants only one cooldown active at a time: the win cooldown below
    # when the daily loss cap hasn't been hit, and the existing kill-lock
    # once it has. See the loss-close handler in close_trade_by_id()/the main
    # close path for the accepted-risk note.
    # ticker_win_cooldown: dict of ticker → ET datetime when the post-win cooldown expires.
    # After a profitable close, the same ticker is blocked for WIN_COOLDOWN_MINUTES to
    # prevent immediately chasing back in (e.g. win on AAPL → lose chasing AAPL 12s later).
    "ticker_win_cooldown":   {},
    # orb_entered_today: set of tickers where the bot already took an ORB entry
    #   this session. ORB breakout conditions persist all session once detected,
    #   so without this guard the bot re-enters the same ORB setup every tick
    #   after the previous trade closes.
    "orb_entered_today":     set(),
    # ── Duplicate-order guard (Fix 3) ────────────────────────────────────────
    # Tracks (contract_symbol, HH:MM) of the most recent order placement.
    # Prevents the same contract from being ordered twice in the same minute,
    # which was causing every signal to generate 2 identical BUY log entries.
    "_last_order_key":       None,
    # ── Sizing / affordability state (surfaced on dashboard so the user can
    #    see what the bot is looking at WITHOUT having to ask) ────────────────
    "last_eval_ticker":      None,   # ticker of the most recently evaluated contract
    "last_eval_opt_type":    None,   # "call" or "put"
    "last_eval_premium":     None,   # raw ask price of that contract
    "last_eval_eff_entry":   None,   # ask price w/ 5% slippage applied
    "last_eval_time":        None,   # HH:MM:SS when it was evaluated
    "last_eval_expiry":      None,   # option expiration date (YYYY-MM-DD)
    "last_eval_strike":      None,   # option strike price
    "risk_budget_usd":       0.0,    # balance x effective_risk_pct — $ at risk if stop hits
    "max_affordable_premium": 0.0,   # highest ask price sizeable to >=1 contract right now
    # ── Network health watchdog ───────────────────────────────────────────────
    # Updated every time a bar fetch succeeds.  Dashboard + bot_state.json
    # expose this so the user can see exactly how long the bot was blind.
    "last_successful_bar_fetch": None,   # ET ISO string of the last clean get_session_bars
    "data_gap_minutes":          0,      # minutes since last clean fetch (0 = healthy)
}

_stop_event    = threading.Event()
_bot_loop_lock = threading.Lock()   # singleton guard — only one trading loop may run at a time
_risk: Optional[RiskManager] = None


def reset_session_state() -> None:
    """
    Hard-reset LIVE_STATE and purge the SIM trade cache from session_state
    whenever the paper/live trading mode is toggled.

    Why this matters:
      • Without a reset, sim trades written to trades_paper.db during a sim
        session remain in LIVE_STATE["open_trade"] when the user switches to
        live mode, causing ghost position displays and incorrect P&L math.
      • The dashboard calls this function immediately after saving the
        paper_trading toggle to user_settings.json.

    What is cleared:
      - All live-session flags (orb_triggered, flip state, watchlist)
      - Open-trade reference (chart will reload from the correct DB next render)
      - Session P&L accumulator
      - ORB stage state and entry tracking
    What is PRESERVED (intentionally):
      - account_balance and last_known_balance (avoids jarring balance jump)
      - scan_watchlist if we're mid-session (will be re-evaluated on next tick)
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


# ── Ticker selection (FIX M8: uses relative volume rank) ─────────────────────

def select_ticker(alpaca: AlpacaClient, tradier: TradierClient, balance: float) -> Optional[str]:
    """
    Phase-based ticker selection:
    Phase 1 (<$25k): SPY and QQQ only — tightest spreads, most liquid options
    Phase 2 ($25k+): Expands to top large-cap movers ranked by relative volume
    Also checks trading window before selecting any ticker.
    """
    from config import get_trading_windows as _gtw

    # Check if we're inside a trading window before doing any work
    _now_et_time = _now_et()   # tz-aware US/Eastern — no manual UTC-4 offset needed
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
        # Phase 1: SPY and QQQ only — rank by relative volume today
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
        # Phase 2+: SPY/QQQ anchors + top 2 large-cap movers by volume
        anchor_tickers  = ["SPY", "QQQ"]
        expanded_pool   = ["NVDA", "META", "MSFT", "GOOGL", "AAPL", "AMZN", "TSLA"]
        bar_dict = {}
        for t in anchor_tickers + expanded_pool:
            bars, err = alpaca.get_bars(t, "5Min", limit=25)
            if not err and bars:
                bar_dict[t] = bars

        ranked = relative_volume_rank(bar_dict)
        # Always include SPY/QQQ, add top 2 movers from expanded pool
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
      5. open_interest ≥ MIN_OPEN_INTEREST (100) — skips illiquid chains

    Logs a debug line for every rejected candidate so the audit trail explains
    exactly why each contract was skipped.

    Returns (contract, info):
      - contract: the selected contract dict, or None if nothing qualified.
      - info: diagnostics dict the caller uses to build an accurate skip
              message — distinguishes "no data from Tradier" vs. "everything
              was simply too expensive for the configured budget":
          info["reason"] is one of:
              "selected"       - a contract was chosen (contract is not None)
              "api_error"      - get_expirations() raised
              "no_expirations" - Tradier returned zero expirations
              "no_chain_data"  - expirations existed but every chain call
                                  returned empty/failed
              "over_budget"    - real chain data was seen, but the cheapest
                                  qualifying contract cost more than max_spend
              "filtered"       - real chain data was seen, but everything was
                                  rejected by the cost-range/spread/OI filters
                                  (not a budget issue)
          info["cheapest_cost"]:   lowest ask*100 among contracts that passed
                                    the cost-range filter but exceeded
                                    max_spend (None if no such contract seen)
          info["cheapest_symbol"]: symbol of that cheapest contract, or None
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

        # First OTM strike closest to current price (cheapest, most liquid)
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
                # Track the cheapest budget-blocked contract so the caller can
                # tell the user exactly how much premium is needed vs. budget.
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
        info["reason"] = "filtered"  # cost-range/spread/OI filtered everything; not a budget issue

    return None, info


# ── Main trading loop ─────────────────────────────────────────────────────────

def run_trading_loop(poll_interval: int = 10) -> None:
    # ── Singleton guard: only ONE trading loop may run at a time ─────────────
    # If a previous loop is still winding down (sleeping between ticks) and
    # Start is pressed again, the new call returns immediately rather than
    # creating a second concurrent loop.  This is the root cause of the
    # 2026-06-18 audit finding where two threads evaluated the same ticker
    # 325ms apart, bypassing loss_cooldown (one saw it, the other didn't).
    if not _bot_loop_lock.acquire(blocking=False):
        logger.warning(
            "run_trading_loop called while another loop is already running — "
            "refusing to start a second concurrent loop."
        )
        log_event(
            "WARNING", "trading_logic",
            "⚠️ Start Bot pressed while a loop is already running — ignored. "
            "Press Stop first, wait a few seconds, then Start again."
        )
        return
    try:
        _stop_event.clear()   # reset stop flag so this new loop can actually run
        _run_trading_loop_inner(poll_interval)
    finally:
        _bot_loop_lock.release()


def _run_trading_loop_inner(poll_interval: int = 10) -> None:
    """Inner body of the trading loop — called exclusively from run_trading_loop()."""
    global _risk
    init_db()
    alpaca, tradier = get_clients()

    try:
        acct    = alpaca.get_account()
        balance = float(acct.get("equity", 0)) if acct else 0
        if balance <= 0:
            balance = float(get_settings().get("last_known_balance", STARTING_CAPITAL))
        else:
            from config import save_settings as _save_start
            _save_start({"last_known_balance": round(balance, 2)})
    except Exception as e:
        logger.error("Cannot fetch account balance: %s", e)
        balance = float(get_settings().get("last_known_balance", STARTING_CAPITAL))

    # FIX: seed LIVE_STATE["account_balance"] immediately, BEFORE the first
    # tick. Previously this key was only set inside _tick()'s market-open
    # branch (line ~738). If the bot starts while the market is CLOSED
    # (e.g. an evening restart), LIVE_STATE["account_balance"] is left at
    # its module-level init value of 0.0 — and because the market-closed
    # branch used LIVE_STATE.get("account_balance", <fallback>), a *present*
    # key with value 0.0 is not "missing", so the fallback to
    # last_known_balance never fired. bot_state.json ended up with
    # "account_balance": 0.0 even though Alpaca/last_known_balance correctly
    # had $5,418.96, and the dashboard showed $0.00.
    LIVE_STATE["account_balance"] = balance

    # FIX: seed LIVE_STATE["session_pnl"] from the database at startup too.
    # Previously "session_pnl" only got recomputed inside _close_position()
    # (sum of today's realized_pnl) whenever a trade CLOSED during this
    # process's lifetime. On restart, the module-level LIVE_STATE dict is
    # recreated with "session_pnl": 0.0 (line ~82) and that 0.0 was written
    # straight to bot_state.json's startup dump below — wiping out any P&L
    # already realized earlier today (e.g. the bot restarted at 19:13 and
    # 19:55 ET, AFTER $121 had already been realized from 5 trades closed
    # earlier this afternoon, so the dashboard's "Session P&L" card showed
    # $0.00 even though the account balance had genuinely grown by $121).
    # Recompute it the same way _close_position() does: sum realized_pnl
    # for every trade whose exit_time falls on today's date.
    try:
        LIVE_STATE["session_pnl"] = sum(
            t.get("realized_pnl", 0) for t in get_all_trades(limit=100)
            if t.get("exit_time", "")[:10] == date.today().isoformat()
        )
    except Exception as e:
        logger.error("Could not recompute session_pnl from DB at startup: %s", e)
        LIVE_STATE["session_pnl"] = 0.0

    _risk = RiskManager(account_balance=balance)
    logger.info(
        "bot_started",
        extra={"event": "bot_started", "account_balance": round(balance, 2)},
    )
    log_event("INFO", "trading_logic", f"🟢 Bot started. Account balance: ${balance:.2f}")
    LIVE_STATE["running"] = True   # lets dashboard detect running state on reload

    # ── Startup reconciliation ────────────────────────────────────────────────
    # Run ghost-position check immediately on start so any positions that filled
    # while the bot was stopped are adopted into the Trade Journal right away
    # rather than waiting for the first trading tick.
    try:
        _startup_ghost = _check_ghost_positions(alpaca)
        LIVE_STATE["ghost_position_alert"] = _startup_ghost
        if _startup_ghost:
            log_event(
                "WARNING", "trading_logic",
                "🟡 Startup reconciliation complete — found and adopted unrecorded "
                "position(s). Check the Trade Journal."
            )
    except Exception as _sg_err:
        logger.warning("startup_reconciliation_failed: %s", _sg_err)

    # Write state immediately so dashboard shows Running before first tick.
    # This is a full overwrite of bot_state.json, which would otherwise wipe
    # "current_option_price"/"current_option_price_time" the instant the bot
    # restarts — even if a position is still held overnight and the market
    # is closed (the dashboard's "Current"/"Unrealised P&L" would then drop
    # back to "–" until the next live tick). Carry those two keys forward
    # from whatever was last written, so a restart never loses the last
    # known option price.
    import json as _json_start, time as _time_start
    _prev_opt_px      = None
    _prev_opt_px_time = None
    try:
        _state_path_start = Path(__file__).resolve().parent / "bot_state.json"
        if _state_path_start.exists():
            with open(_state_path_start) as _f:
                _prev_state = _json_start.load(_f)
            _prev_opt_px      = _prev_state.get("current_option_price")
            _prev_opt_px_time = _prev_state.get("current_option_price_time")
    except Exception:
        pass
    LIVE_STATE["current_option_price"]      = _prev_opt_px
    LIVE_STATE["current_option_price_time"] = _prev_opt_px_time
    try:
        _state_path_start = Path(__file__).resolve().parent / "bot_state.json"
        _json_start.dump({
            "running":         True,
            "account_balance": float(balance),
            "session_pnl":     LIVE_STATE.get("session_pnl", 0.0),
            "status":          "starting",
            "current_ticker":  None,
            "last_signal":     None,
            "market_open":     False,
            "last_update":     _time_start.strftime("%H:%M:%S"),
            "current_option_price":      _prev_opt_px,
            "current_option_price_time": _prev_opt_px_time,
        }, open(_state_path_start, "w"))
    except Exception:
        pass

    while not _stop_event.is_set():
        try:
            # ── Daily scan: build dynamic universe once per session ───────────
            # Runs during 09:00–11:30 ET window. The scan itself waits for
            # 9:30 open before computing gaps — pre-market calls return the
            # previous universe as a placeholder until the open bar is available.
            if not LIVE_STATE.get("scanner_ran_today") and is_scan_window():
                try:
                    wl = run_scan(alpaca, max_tickers=10)
                    LIVE_STATE["scan_watchlist"] = wl
                    LIVE_STATE["scan_idx"]       = 0
                    if wl:
                        LIVE_STATE["current_ticker"] = wl[0]

                    # Only mark the scan done when the FULL scan has run.
                    # daily_premarket_scan() returns the pre-market fallback
                    # (SPY/QQQ) WITHOUT writing daily_universe.json when called
                    # before 9:30 ET. We detect this by checking whether the
                    # file now carries today's date. If not, the real scan
                    # hasn't fired yet — leave scanner_ran_today=False so the
                    # next tick retries and eventually gets the full 9:30+ scan.
                    from scanner import _read_daily_universe, _et_now as _scanner_et_now
                    _du = _read_daily_universe()
                    _full_scan_ran = (_du.get("date") == _scanner_et_now().strftime("%Y-%m-%d"))
                    LIVE_STATE["scanner_ran_today"] = _full_scan_ran

                    _label = "🟢 Scan complete" if _full_scan_ran else "🟡 Pre-market (waiting for 9:30 open)"
                    logger.info("scan_tick", extra={
                        "event": "scan_tick", "watchlist": wl,
                        "full_scan": _full_scan_ran,
                    })
                    log_event("INFO", "scanner",
                              f"{_label}. Watchlist: {', '.join(wl)}")
                except Exception as _ex:
                    logger.warning("Pre-market scan failed: %s — using anchors", _ex)
                    LIVE_STATE["scan_watchlist"]    = ["SPY", "QQQ"]
                    LIVE_STATE["scanner_ran_today"] = False  # retry next tick
                    LIVE_STATE["current_ticker"]    = "SPY"

            _tick(alpaca, tradier)

        except DailyLossLimitReached as e:
            LIVE_STATE["status"] = "kill_locked"
            send_alert("DAILY LOSS LIMIT — KILL LOCK ACTIVE", str(e))
            # Close any open positions immediately before the freeze
            try:
                _panic_close_all_positions(alpaca, tradier)
            except Exception as _ce:
                logger.error("Panic close on kill lock failed: %s", _ce)
            logger.warning("kill_lock_sleep: trading halted for 24h")
            # Sleep in 5-minute increments so the loop is responsive to stop signal
            for _ in range(288):          # 288 × 5 min = 24 h
                if _stop_event.is_set():
                    break
                time.sleep(300)
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.exception("Unexpected error in trading loop: %s", e)
            log_event("ERROR", "trading_logic",
                      f"🔴 Unexpected error in trading loop: {type(e).__name__}. "
                      f"Bot will retry on next tick. ({e})")
            send_alert("CRITICAL ERROR", str(e))
            # Push error status so the dashboard audit log and status badge
            # update instead of freezing on stale data.
            LIVE_STATE["status"]      = "error"
            LIVE_STATE["last_update"] = _now_et().isoformat()
            try:
                import json as _jerr, pathlib as _perr
                _jerr.dump({
                    "running":    True,
                    "status":     "error",
                    "last_error": str(e)[:200],
                    "last_update": LIVE_STATE["last_update"],
                    "account_balance": LIVE_STATE.get("account_balance", 0),
                    "market_open": LIVE_STATE.get("market_open", False),
                }, open(_perr.Path(__file__).parent / "bot_state.json", "w"))
            except Exception:
                pass
            time.sleep(30)

        # Smart sleep: scan every 10s during trading window, every 60s outside
        # Uses phase-based windows from config — auto-expands at $25k
        from config import get_trading_windows as _gtw
        _now_et_sl = _now_et()   # tz-aware US/Eastern
        _hm        = _now_et_sl.hour * 60 + _now_et_sl.minute
        _balance = LIVE_STATE.get("account_balance", 0)
        _windows = _gtw(_balance)
        _in_window = any(
            int(s.split(":")[0]) * 60 + int(s.split(":")[1]) <= _hm <=
            int(e.split(":")[0]) * 60 + int(e.split(":")[1])
            for s, e in _windows
        )
        time.sleep(poll_interval if _in_window else 60)

    logger.info("Trading loop stopped")


def _log_bar_thinking(df1m: "pd.DataFrame", df5: "pd.DataFrame", ticker: str) -> None:
    """
    Emit one human-readable 🟡 audit log entry per newly closed 1-min candle.

    df1m  — today's 1-min bars (drives narrative timing and current price/time)
    df5   — 5-min bars augmented with history (used for ORB range + RVOL/VWAP
            calculations, which need multi-day context to be meaningful)

    Uses LIVE_STATE["last_logged_1m_bar_time"] to log each 1-min bar exactly once.
    """
    try:
        if df1m is None or df1m.empty:
            return

        import pandas as _pd
        from signals import (
            get_opening_range  as _get_or,
            compute_vwap       as _cvwap,
            compute_rvol       as _crvol,
            ORB_RVOL_THRESHOLD as _ORB_RVOL,
        )

        # ── 1-min: isolate today and get the most recent closed bar ──────────
        latest_date_1m = df1m["time"].dt.date.max()
        today_1m       = df1m[df1m["time"].dt.date == latest_date_1m].reset_index(drop=True)
        if len(today_1m) < 2:
            return

        last_bar     = today_1m.iloc[-1]
        bar_time_str = str(last_bar["time"])

        # Skip if we already logged this 1-min bar
        if LIVE_STATE.get("last_logged_1m_bar_time") == bar_time_str:
            return
        LIVE_STATE["last_logged_1m_bar_time"] = bar_time_str

        close   = float(last_bar["close"])
        bar_t   = bar_time_str[11:16]   # HH:MM portion for display

        # ── 5-min: today's slice used for ORB detection ───────────────────────
        latest_date_5m = df5["time"].dt.date.max()
        today_df       = df5[df5["time"].dt.date == latest_date_5m].reset_index(drop=True)

        # ── Opening Range ─────────────────────────────────────────────────────
        or_info = _get_or(today_df)
        if or_info is None:
            log_event("INFO", "bar_eval",
                      f"🟡 [{ticker}] {bar_t} — Waiting for the 9:30 opening candle to form. "
                      f"Holding off until the Opening Range is set.")
            return

        or_high = or_info["high"]
        or_low  = or_info["low"]

        # ── VWAP ──────────────────────────────────────────────────────────────
        vwap_series = _cvwap(today_df)
        vwap_val    = float(vwap_series.iloc[-1]) if not _pd.isna(vwap_series.iloc[-1]) else None

        # ── RVOL — uses the full augmented 5-min df for historical context ──────
        rvol_series = _crvol(df5, lookback_days=10)
        rvol_today  = rvol_series.reindex(today_df.index)
        rvol_val    = float(rvol_today.iloc[-1]) if not _pd.isna(rvol_today.iloc[-1]) else 0.0

        # ── Plain-English volume description ──────────────────────────────────
        if rvol_val >= 2.0:
            vol_desc = f"Volume is very elevated ({rvol_val:.1f}× normal) — strong conviction."
        elif rvol_val >= _ORB_RVOL:
            vol_desc = f"Volume is above average ({rvol_val:.1f}× normal) ✓"
        elif rvol_val >= 0.7:
            vol_desc = f"Volume is light ({rvol_val:.1f}× normal) — waiting for confirmation."
        else:
            vol_desc = f"Volume is very low ({rvol_val:.1f}× normal) — not enough activity yet."

        # ── VWAP relationship ─────────────────────────────────────────────────
        if vwap_val is not None:
            vwap_diff_pct = (close - vwap_val) / vwap_val * 100
            if close > vwap_val:
                vwap_desc = f"Price is above VWAP (${vwap_val:.2f}) — buyers in control."
            elif close < vwap_val:
                vwap_desc = f"Price is below VWAP (${vwap_val:.2f}) — sellers in control."
            else:
                vwap_desc = f"Price is sitting right at VWAP (${vwap_val:.2f})."
        else:
            vwap_desc = "VWAP not yet available."

        # ── Price vs Opening Range ────────────────────────────────────────────
        if close > or_high:
            price_desc = f"Price (${close:.2f}) broke ABOVE the Opening Range high (${or_high:.2f})."
            bias       = "CALL"
            # Check if all conditions align for a bullish signal
            if rvol_val >= _ORB_RVOL and vwap_val is not None and close > vwap_val:
                narrative = (
                    f"🟡 [{ticker}] {bar_t} 1m — {price_desc} "
                    f"{vol_desc} {vwap_desc} "
                    f"All conditions align for a CALL setup — evaluating entry."
                )
            elif rvol_val < _ORB_RVOL:
                narrative = (
                    f"🟡 [{ticker}] {bar_t} 1m — {price_desc} "
                    f"{vol_desc} Need more buying volume before entering a CALL."
                )
            else:
                narrative = (
                    f"🟡 [{ticker}] {bar_t} 1m — {price_desc} "
                    f"{vol_desc} {vwap_desc} "
                    f"Watching for VWAP to confirm the CALL bias."
                )

        elif close < or_low:
            price_desc = f"Price (${close:.2f}) broke BELOW the Opening Range low (${or_low:.2f})."
            bias       = "PUT"
            if rvol_val >= _ORB_RVOL and vwap_val is not None and close < vwap_val:
                narrative = (
                    f"🟡 [{ticker}] {bar_t} 1m — {price_desc} "
                    f"{vol_desc} {vwap_desc} "
                    f"All conditions align for a PUT setup — evaluating entry."
                )
            elif rvol_val < _ORB_RVOL:
                narrative = (
                    f"🟡 [{ticker}] {bar_t} 1m — {price_desc} "
                    f"{vol_desc} Need more selling volume before entering a PUT."
                )
            else:
                narrative = (
                    f"🟡 [{ticker}] {bar_t} 1m — {price_desc} "
                    f"{vol_desc} {vwap_desc} "
                    f"Watching for VWAP to confirm the PUT bias."
                )

        else:
            # Price inside the Opening Range
            dist_to_high = or_high - close
            dist_to_low  = close - or_low
            if dist_to_high < dist_to_low:
                proximity = f"near the top of the range (${or_high:.2f})"
            else:
                proximity = f"near the bottom of the range (${or_low:.2f})"
            narrative = (
                f"🟡 [{ticker}] {bar_t} 1m — Candle closed inside the Opening Range "
                f"(${or_low:.2f}–${or_high:.2f}), {proximity}. "
                f"{vol_desc} {vwap_desc} "
                f"Waiting for a clear breakout before taking any position."
            )

        log_event("INFO", "bar_eval", narrative)

    except Exception as _be:
        logger.debug("_log_bar_thinking error: %s", _be)


# ── Ghost-position reconciliation ───────────────────────────────────────────
# FIX: on 2026-06-15, Alpaca's options buying power dropped to $52.55 and the
# account balance fell ~$375 while trades_paper.db showed nothing open and
# Session P&L stayed flat. That combination means Alpaca was holding a
# position the bot's own database didn't know about — so the bot's exit logic
# (stop-loss / 45-min time-box) never managed it, Session P&L never reflected
# its loss, and it silently ate the buying power every new order needed.
# This check compares Alpaca's actual open positions against
# get_open_trade() every tick and raises a one-time CRITICAL alert (plus a
# persistent dashboard banner via bot_state.json) the moment they disagree —
# so this can be caught and resolved within minutes instead of hours.
_ghost_alert_logged = False


def _check_ghost_positions(alpaca: AlpacaClient) -> Optional[dict]:
    """
    Returns a dict describing any Alpaca position(s) not tracked in
    trades_paper.db, or None if Alpaca's positions agree with the DB
    (or the positions fetch itself failed — don't alert on a transient
    network hiccup).

    Two classes of "position in Alpaca but not in open DB":
      1. FAILED-CLOSE: The bot already closed the trade in the DB
         (status='closed') but the Alpaca sell order never filled.
         Action → silently retry the close via alpaca.close_position().
      2. TRUE GHOST: No DB record at all (order placed outside the bot,
         or placed but DB write crashed).
         Action → alert so the user knows and can close manually.
    """
    global _ghost_alert_logged
    try:
        positions = alpaca.get_positions()
    except Exception:
        return None

    # Compare against the FULL SET of tracked open trades — with
    # MAX_CONCURRENT_POSITIONS=2, both legs are legitimate, so only a
    # position whose symbol matches NEITHER tracked trade is a "ghost".
    db_open    = get_open_trades()
    db_symbols = {t.get("contract_symbol") for t in db_open}
    ghosts     = [p for p in positions if p.get("symbol") not in db_symbols]

    if not ghosts:
        _ghost_alert_logged = False   # reset so a future ghost re-alerts
        return None

    # ── Classify each ghost ───────────────────────────────────────────────────
    # Query all trades closed TODAY whose symbol is in the ghost list.
    # These are "failed-close" positions — the bot closed them in the DB
    # but the Alpaca sell order timed out or wasn't confirmed.
    ghost_symbols = {p.get("symbol") for p in ghosts}
    try:
        with get_conn() as _gc:
            _today_str = _now_et().strftime("%Y-%m-%d")
            _closed_today = _gc.execute(
                """SELECT contract_symbol FROM trades
                   WHERE status='closed'
                   AND date(exit_time) = ?""",
                (_today_str,),
            ).fetchall()
        failed_close_symbols = {r[0] for r in _closed_today} & ghost_symbols
    except Exception as _dbe:
        logger.warning("ghost_classify_db_error: %s", _dbe)
        failed_close_symbols = set()

    # ── Auto-retry close for failed-close positions ───────────────────────────
    for p in ghosts:
        sym = p.get("symbol", "")
        if sym in failed_close_symbols:
            try:
                alpaca.close_position(sym)
                log_event(
                    "WARNING", "reconciliation",
                    f"🟡 FAILED-CLOSE RETRY — {sym} was marked closed in the journal "
                    f"but Alpaca still showed it open. Auto-retrying the close order now."
                )
                logger.warning(
                    "failed_close_retry",
                    extra={"event": "failed_close_retry", "symbol": sym},
                )
            except Exception as _ce:
                logger.error("failed_close_retry error for %s: %s", sym, _ce)

    # ── Auto-adopt TRUE ghosts into the journal ───────────────────────────────
    # A true ghost has no DB record at all — the order filled in Alpaca but
    # insert_trade() was never called (timeout, crash, or 403 that slipped
    # through the cancellation logic). Auto-adopting creates an open DB record
    # so the position appears in the Trade Journal immediately and the bot's
    # stop-loss / time-box logic can manage it on the next tick.
    import re as _re
    true_ghosts = [p for p in ghosts if p.get("symbol") not in failed_close_symbols]
    if not true_ghosts:
        _ghost_alert_logged = False
        return None

    still_unrecorded = []   # any we failed to adopt (bad symbol format, etc.)
    for p in true_ghosts:
        sym = p.get("symbol", "")
        # Parse OCC symbol: e.g. SPY260624C00754000
        _m = _re.match(r'^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$', sym)
        if not _m:
            still_unrecorded.append(p)
            continue
        _tkr, _yy, _mo, _dy, _cp, _strike_raw = _m.groups()
        _expiry    = f"20{_yy}-{_mo}-{_dy}"
        _opt_type  = "call" if _cp == "C" else "put"
        _strike    = float(_strike_raw) / 1000.0
        try:
            _qty = int(p.get("qty") or 1)
            # Alpaca cost_basis = total cost (premium * qty * 100 multiplier)
            _cost = float(p.get("cost_basis") or 0)
            _entry_px = (_cost / _qty / 100) if _qty else 0.0
            # avg_entry_price takes priority if Alpaca provides it
            if p.get("avg_entry_price"):
                _entry_px = float(p["avg_entry_price"])
            _trade_id = insert_trade(
                ticker          = _tkr,
                contract_symbol = sym,
                option_type     = _opt_type,
                strike          = _strike,
                expiry          = _expiry,
                contracts       = _qty,
                entry_price     = _entry_px,
                entry_time      = _now_et(),
                entry_reason    = "Recovered from Alpaca — bot entered before DB write",
                paper           = True,
                strategy_id     = "RECOVERED_UNTRACKED",
            )
            log_event(
                "WARNING", "reconciliation",
                f"🟡 AUTO-ADOPTED ghost position {sym} (trade #{_trade_id}) into "
                f"the Trade Journal. The bot will now manage its stop-loss and "
                f"time-box going forward."
            )
            logger.warning(
                "ghost_auto_adopted",
                extra={"event": "ghost_auto_adopted", "symbol": sym, "trade_id": _trade_id},
            )
        except Exception as _ae:
            logger.error("ghost_auto_adopt_failed for %s: %s", sym, _ae)
            still_unrecorded.append(p)

    if not still_unrecorded:
        _ghost_alert_logged = False
        return None

    # Only alert for positions we couldn't parse/adopt
    if not _ghost_alert_logged:
        for p in still_unrecorded:
            logger.critical(
                "ghost_position_detected",
                extra={
                    "event":         "ghost_position_detected",
                    "symbol":        p.get("symbol"),
                    "qty":           p.get("qty"),
                    "market_value":  p.get("market_value"),
                    "unrealized_pl": p.get("unrealized_pl"),
                    "cost_basis":    p.get("cost_basis"),
                },
            )
            log_event(
                "CRITICAL", "reconciliation",
                f"🚨 GHOST POSITION — could not auto-adopt {p.get('symbol')} "
                f"(unrecognised symbol format). Check Alpaca Positions tab and "
                f"close it manually if needed."
            )
        _ghost_alert_logged = True

    return {
        "detected_at": _now_et().isoformat(),
        "positions": [
            {
                "symbol":        p.get("symbol"),
                "qty":           p.get("qty"),
                "market_value":  p.get("market_value"),
                "unrealized_pl": p.get("unrealized_pl"),
            }
            for p in still_unrecorded
        ],
    }


def _sweep_orphaned_orders(alpaca: AlpacaClient, open_trades: list[dict]) -> None:
    """
    Cancel any resting Alpaca order whose symbol doesn't belong to a
    currently-tracked open trade.

    FIX 2026-06-15 (ghost positions, MAX_CONCURRENT_POSITIONS follow-up): a
    failed order placement can leave behind a resting limit order at the
    broker even though the bot has no DB record of it. If left alone, that
    order can fill hours later, unsupervised, with no stop-loss/profit-target
    — exactly the "ghost position" bug fixed earlier today. place_option_order
    already sweeps for this on its OWN symbol right after a failed placement,
    but this per-tick sweep is a second safety net that catches orphans from
    ANY symbol (e.g. left over from a bot restart or a previous failed tick).
    """
    try:
        open_orders = alpaca.get_open_orders()
    except Exception as e:
        logger.warning("_sweep_orphaned_orders: get_open_orders failed: %s", e)
        return
    if not open_orders:
        return

    tracked_symbols = {t.get("contract_symbol") for t in open_trades}
    for o in open_orders:
        _sym = o.get("symbol")
        if _sym in tracked_symbols:
            continue
        _oid = o.get("id", "")
        if alpaca.cancel_order(_oid):
            log_event(
                "WARNING", "reconciliation",
                f"🟡 Cancelled an orphaned resting order for {_sym} "
                f"(order ID: {_oid[:8]}…) that wasn't tied to any open "
                f"position the bot is tracking — it could have filled "
                f"unsupervised as a ghost position."
            )
            logger.warning(
                "orphan_order_swept",
                extra={"event": "orphan_order_swept", "symbol": _sym, "order_id": _oid},
            )


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
    LIVE_STATE["last_eval_ticker"]    = ticker
    LIVE_STATE["last_eval_opt_type"]  = opt_type
    LIVE_STATE["last_eval_premium"]   = ask_price
    LIVE_STATE["last_eval_eff_entry"] = eff_entry
    LIVE_STATE["last_eval_time"]      = _time.strftime("%H:%M:%S")
    LIVE_STATE["last_eval_expiry"]    = contract.get("expiry")
    LIVE_STATE["last_eval_strike"]    = contract.get("strike")
    try:
        with open(_state_path) as _f:
            _bs = _json.load(_f)
        _bs["last_eval_ticker"]       = ticker
        _bs["last_eval_opt_type"]     = opt_type
        _bs["last_eval_premium"]      = ask_price
        _bs["last_eval_eff_entry"]    = eff_entry
        _bs["last_eval_time"]         = LIVE_STATE["last_eval_time"]
        _bs["last_eval_expiry"]       = LIVE_STATE["last_eval_expiry"]
        _bs["last_eval_strike"]       = LIVE_STATE["last_eval_strike"]
        _bs["risk_budget_usd"]        = round(balance * _risk.effective_risk_pct(balance), 2)
        _bs["max_affordable_premium"] = _risk.max_affordable_premium(balance)
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

    confirmed_price = order.get("confirmed_fill_price", ask_price)
    entry_utc       = _now_et()   # tz-aware ET — stored as ET ISO in DB

    # ── Record to database ────────────────────────────────────────────────────
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


# ── Position management ────────────────────────────────────────────────────────

def _manage_open_position(
    alpaca: AlpacaClient,
    tradier: TradierClient,
    trade: dict,
    balance: float,
) -> None:
    """
    ORB two-stage exit manager.

    Stage 1: sell 50% of contracts when current_price ≥ entry × 1.50.
             Remainder's stop moves to break-even (entry_price).

    Stage 2: hold remainder until:
      a) Price falls to break-even (entry_price) → exit remainder.
      b) 45-minute time-box from entry_time → exit remainder.
      c) Hard stop (30% below entry) triggers before stage 1 → exit all.

    Uses single-contract Tradier quote (no full chain fetch) to minimise latency.
    Entry time is stored in LIVE_STATE["entry_time"] (ISO UTC string).
    """
    try:
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote is None:
            logger.warning("Cannot price %s — holding", trade["contract_symbol"])
            return

        current_price = quote["mid"]
        entry_price   = trade["entry_price"]
        trade_id      = trade["id"]

        # ── Per-position state (NEW — MAX_CONCURRENT_POSITIONS) ───────────────
        # Each open trade has its own slot in LIVE_STATE["positions"], keyed by
        # trade_id, so a 2nd concurrent position's peak/stage/stop tracking
        # never collides with the 1st's. setdefault() covers the case where
        # this trade was opened in a PREVIOUS bot run (restart recovery) and
        # therefore has no in-memory entry yet.
        ps = LIVE_STATE["positions"].setdefault(trade_id, {
            "peak_price":                None,
            "entry_time":                trade.get("entry_time"),
            "stage1_done":               False,
            "stage1_be_price":           None,
            "current_stop_pct":          _risk.ORB_STOP_PCT if _risk else 0.30,
            "struct_stop_price":         None,
            "current_option_price":      None,
            "current_option_price_time": None,
            "last_position_narration_minute": None,
        })

        # Publish the live OPTION premium to this position's state so the
        # dashboard can compute unrealised P&L correctly (current option
        # price - entry option price), instead of mixing it with the
        # underlying stock price.
        # NOTE: the dashboard runs as a SEPARATE PROCESS with its own copy of
        # LIVE_STATE, so this in-memory write alone is invisible to it — it's
        # bridged to bot_state.json a few lines below (merged alongside
        # current_stop_pct) so the dashboard's _read_bot_state() can see it.
        ps["current_option_price"]      = current_price
        ps["current_option_price_time"] = _now_et().strftime("%H:%M:%S")

        # Recover entry_time from per-position state (may be missing after restart)
        entry_time_iso = ps.get("entry_time") or trade.get("entry_time")
        try:
            entry_time = datetime.fromisoformat(entry_time_iso) if entry_time_iso else None
            # FIX: trade["entry_time"] comes from the DB via
            # database._to_et_isoformat(), which stores tz-NAIVE ET strings
            # (so chart timestamps line up). _now_et() below is tz-AWARE ET.
            # Subtracting naive - aware raises TypeError, which was firing on
            # every tick for any position carried across a restart. Localize
            # naive timestamps to ET so they match now_utc.
            if entry_time is not None and entry_time.tzinfo is None:
                entry_time = _ET_TZ.localize(entry_time)
        except Exception:
            entry_time = None

        # Recover peak for DB compatibility (not used in ORB logic but kept for audit)
        if ps.get("peak_price") is None:
            recovered = recover_peak_price(trade_id)
            ps["peak_price"] = recovered or entry_price

        peak_price = max(ps["peak_price"], current_price)
        if peak_price > ps["peak_price"]:
            ps["peak_price"] = peak_price
            persist_peak_price(trade_id, peak_price)

        stage1_done     = bool(ps.get("stage1_done"))
        stage1_be_price = ps.get("stage1_be_price")
        now_utc         = _now_et()   # tz-aware ET (variable name kept for minimal diff)

        # ── Recompute dynamic stop and publish to state each tick ─────────────
        # Tightens 5pp every 15 min so the dashboard always shows the live stop
        # and bot_state.json is correct even after a restart.
        current_stop_pct = _risk.dynamic_stop_pct(entry_time, now_utc)
        ps["current_stop_pct"] = current_stop_pct

        # Persist to bot_state.json so the restart-recovery path has it.
        # NEW (MAX_CONCURRENT_POSITIONS): write a per-trade entry under
        # "open_positions" (keyed by trade_id) instead of a single set of
        # top-level fields, so 2 concurrent positions don't overwrite each
        # other in the bridge file. The dashboard's _read_bot_state() looks
        # up this trade's entry by trade_id.
        import json as _json_m
        _state_path_m = __import__("pathlib").Path(__file__).resolve().parent / "bot_state.json"
        try:
            _existing = {}
            if _state_path_m.exists():
                with open(_state_path_m) as _f:
                    _existing = _json_m.load(_f)
            _open_positions = _existing.get("open_positions") or {}
            _open_positions[str(trade_id)] = {
                "trade_id":                  trade_id,
                "contract_symbol":           trade.get("contract_symbol"),
                "ticker":                    trade.get("ticker"),
                "option_type":               trade.get("option_type"),
                "entry_price":               entry_price,
                "contracts":                 trade.get("contracts"),
                "current_stop_pct":          current_stop_pct,
                "current_option_price":      current_price,
                "current_option_price_time": ps["current_option_price_time"],
                "stage1_done":               stage1_done,
                "peak_price":                ps["peak_price"],
                "entry_time":                entry_time_iso,
            }
            _existing["open_positions"] = _open_positions
            # Legacy top-level fields — mirror the FIRST open position so any
            # not-yet-updated dashboard code paths still show something
            # sensible rather than a blank/"–" value.
            _existing["current_stop_pct"]          = current_stop_pct
            _existing["current_option_price"]      = current_price
            _existing["current_option_price_time"] = ps["current_option_price_time"]
            with open(_state_path_m, "w") as _f:
                _json_m.dump(_existing, _f)
        except Exception:
            pass

        # Structural stop: entry_bar_high-derived option level (VWAP_PB / CHAN_BREAK)
        # Set at entry, persists in this position's state until it's closed.
        _struct_stop = ps.get("struct_stop_price")

        # ── Per-minute "still in trade" narration ─────────────────────────────
        # While a position is open, _tick() returns immediately after this
        # function (skipping _log_bar_thinking()), so the audit log previously
        # went silent except for sparse "trade_id=N peak=X" rows — those are
        # only written by persist_peak_price() on a NEW high. Add a
        # once-per-minute human-readable update so the audit log keeps
        # narrating what the bot sees while holding.
        _minute_key = now_utc.strftime("%Y-%m-%d %H:%M")
        if ps.get("last_position_narration_minute") != _minute_key:
            ps["last_position_narration_minute"] = _minute_key
            _contracts = trade.get("contracts", 1)
            _pnl_now   = (current_price - entry_price) * _contracts * 100
            _pnl_pct   = (current_price - entry_price) / entry_price * 100 if entry_price else 0.0
            _stop_px   = entry_price * (1 - current_stop_pct)
            if entry_time is not None:
                _elapsed_min = (now_utc - entry_time).total_seconds() / 60
                _remain_min  = max(0, 45 - _elapsed_min)
                _time_desc   = f"{_remain_min:.0f} min left in the 45-min window"
            else:
                _time_desc = "time-box unknown (entry time missing)"
            _stage_desc = "Stage 2 — runner, stop at break-even" if stage1_done else "Stage 1 — full size"
            log_event(
                "INFO", "position_update",
                f"🟡 [{trade['contract_symbol']}] Holding — option @ ${current_price:.2f} "
                f"(entry ${entry_price:.2f}, peak ${ps['peak_price']:.2f}). "
                f"P&L {'+' if _pnl_now >= 0 else ''}${_pnl_now:.2f} ({_pnl_pct:+.1f}%). "
                f"Stop ${_stop_px:.2f} ({current_stop_pct*100:.0f}% below entry). "
                f"{_stage_desc}. {_time_desc}."
            )

        should_exit, reason = _risk.should_exit(
            entry_price, current_price,
            entry_time=entry_time,
            now=now_utc,
            stage1_done=stage1_done,
            stage1_be_price=stage1_be_price,
            struct_stop_price=_struct_stop,
        )

        if not should_exit:
            return

        if reason.startswith("stage1"):
            # ── Stage 1: sell half, lock in trail stop on remainder ───────────
            half_contracts = max(1, trade["contracts"] // 2)

            # ── Single-contract guard: can't sell half of 1 ──────────────────
            # With only 1 contract, `half_contracts` == `trade["contracts"]`
            # (max(1, 0) == 1). Executing "Stage 1" would sell ALL contracts,
            # leaving a zombie open trade with 0 contracts and a Stage 2 stop
            # running on nothing. Instead, take the full +50% win immediately —
            # a single-contract account can't do a partial exit, so the clean
            # move is closing the whole thing at the profit target.
            if half_contracts >= trade["contracts"]:
                log_event(
                    "INFO", "trading_logic",
                    f"🟢 [{trade['ticker']}] +50% target hit — only "
                    f"{trade['contracts']} contract(s) held, taking full exit "
                    f"(partial exit impossible on single contract). Closing now.",
                )
                _close_position(alpaca, trade, current_price,
                                "stage1_50pct_full_exit_single_contract")
                return

            settings = get_settings()
            paper    = settings.get("paper_trading", True)

            if paper:
                _trade_log.info(
                    "stage1_partial_exit",
                    extra={
                        "event":        "stage1_partial_exit",
                        "contracts_sold": half_contracts,
                        "exit_price":   round(current_price, 4),
                        "entry_price":  round(entry_price, 4),
                    },
                )
            # Route through broker regardless of paper mode — ALPACA_BASE_URL
            # in .env determines paper vs live destination.
            fill = alpaca.place_option_order(
                symbol      = trade["contract_symbol"],
                qty         = half_contracts,
                side        = "sell",
                order_type  = "market",
            )

            # FIX 2026-06-15 (data-integrity): place_option_order() returns
            # None on a rejected/timed-out order (broker.py _wait_for_fill).
            # The OLD code marked stage1 "done" and moved the stop to
            # break-even REGARDLESS of whether the sell actually executed —
            # on 2026-06-15 this happened to trade 62 (JPM), whose stage1
            # sell was rejected by Alpaca with "account not eligible to
            # trade uncovered option contracts" (a 403). The DB/Alpaca
            # position was untouched, but ps["stage1_done"] was set to True
            # anyway, silently corrupting this position's exit logic
            # (break-even stop on a "remainder" that was never reduced).
            #
            # Now: if the order didn't fill, leave stage1_done False and
            # retry next tick — exactly like a normal failed entry order.
            if fill is None:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take order "
                    f"did not fill — position left at full size, will retry "
                    f"next tick.",
                )
                return

            # FIX 2026-06-15 (data-integrity): the OLD code never wrote the
            # stage-1 partial close back to the `trades` table — only
            # in-memory/bot_state `ps["stage1_done"]` was updated. On
            # 2026-06-15 this caused trade 60 (GS) to sell 2 of 4 contracts
            # for a real +$138 gain at Alpaca while the DB still showed all
            # 4 contracts open with no exit recorded (had to be manually
            # reconciled afterward). Now: split the partial close into its
            # own CLOSED row (using the broker-confirmed fill price when
            # available) and shrink the original trade's `contracts` to the
            # remainder, so the journal always matches what Alpaca holds.
            fill_price = float(fill.get("filled_avg_price") or current_price)

            partial_id = insert_trade(
                ticker          = trade["ticker"],
                contract_symbol = trade["contract_symbol"],
                option_type     = trade["option_type"],
                strike          = trade["strike"],
                expiry          = trade["expiry"],
                contracts       = half_contracts,
                entry_price     = entry_price,
                entry_time      = trade["entry_time"] if isinstance(trade["entry_time"], datetime) else datetime.fromisoformat(trade["entry_time"]),
                entry_reason    = trade.get("entry_reason", ""),
                paper           = paper,
                strategy_id     = trade.get("strategy_id", "INST_ORB"),
            )
            partial_pnl = close_trade(
                trade_id            = partial_id,
                exit_price          = fill_price,
                exit_time           = _now_et().replace(tzinfo=None),
                exit_reason         = "stage1_50pct_profit_take",
                confirmed_fill_price= fill_price,
            )

            with get_conn() as _conn:
                _conn.execute(
                    "UPDATE trades SET contracts = ? WHERE id = ?",
                    (trade["contracts"] - half_contracts, trade["id"]),
                )

            log_event(
                "INFO", "trading_logic",
                f"🟢 Took 50% profit — sold {half_contracts} contract"
                f"{'s' if half_contracts > 1 else ''} at ${fill_price:.2f} "
                f"(+${partial_pnl:.2f}). Stop moved to break-even on the remainder.",
            )

            # Move state to stage 2:
            # Trail floor moves from break-even (entry) UP to entry × 1.15 —
            # this locks in a 15% profit on the remainder instead of letting it
            # ride all the way back to zero.  evaluate_exit_conditions() in
            # risk.py reads this value as the stage2 stop trigger.
            ps["stage1_done"]     = True
            ps["stage1_be_price"] = round(entry_price * (1.0 + STAGE2_TRAIL_PCT), 4)

        else:
            # ── Full exit (stop_loss, time_box, stage2 BE, or stage2 stop) ────
            _close_position(alpaca, trade, current_price, reason)

    except Exception as e:
        logger.error("Error managing ORB position: %s", e)
        log_event("ERROR", "trading_logic",
                  f"🔴 Error while monitoring open position: {type(e).__name__}. "
                  f"Will retry next tick. ({e})")


def _close_position(
    alpaca: AlpacaClient,
    trade: dict,
    exit_price: float,
    reason: str,
) -> None:
    global _trade_log   # declared at top so all uses below are valid
    settings = get_settings()
    paper    = settings.get("paper_trading", True)

    # Resolve current risk tier for the close audit record (was always "unknown" before)
    _balance_close  = LIVE_STATE.get("account_balance", STARTING_CAPITAL)
    _rpct_close     = get_risk_tier(_balance_close)
    _tier_label = (
        "Tier4_5pct" if _rpct_close >= BOOTSTRAP_RISK_PCT else
        "Tier3_3pct" if _rpct_close >= _GMT_TL else
        "Tier2_2pct" if _rpct_close >= _MTT_TL else
        "Tier1_1pct"
    )

    if paper:
        logger.info("[PAPER] SELL %s @ $%.4f (%s)", trade["contract_symbol"], exit_price, reason)
    # Route through broker regardless of paper mode — ALPACA_BASE_URL in .env
    # determines paper vs live destination.
    fill = alpaca.place_option_order(
        symbol      = trade["contract_symbol"],
        qty         = trade["contracts"],
        side        = "sell",
        order_type  = "market",
    )

    # FIX 2026-06-15: use the broker-confirmed fill price for P&L, not the
    # Tradier mid-quote at trigger time. Previously the bot recorded exit_price
    # = Tradier mid at the moment the exit signal fired, which diverged from
    # the actual Alpaca fill due to bid/ask spread, slippage, and (worst case)
    # overnight decay when a market order sat in a "day" order queue until the
    # next session open. confirmed_fill_price overrides exit_price inside
    # close_trade() when provided.
    fill_price = exit_price  # fallback if order returns None (e.g. paper sim)
    if fill and fill.get("filled_avg_price"):
        fill_price = float(fill["filled_avg_price"])

    pnl = close_trade(
        trade_id             = trade["id"],
        exit_price           = exit_price,       # trigger price — kept for audit trail
        exit_time            = _now_et(),
        exit_reason          = reason,
        confirmed_fill_price = fill_price,       # actual fill used for P&L
    )

    # ── Human-readable close narrative for the Audit Log ─────────────────────
    try:
        _ticker_close = trade.get("ticker", "?")
        _opt_close    = trade.get("option_type", "option").upper()
        _entry_px     = trade.get("entry_price", 0)
        _pnl_sign     = "+" if pnl >= 0 else ""
        _reason_map   = {
            "time_box_45m":              "45-minute time limit reached",
            "stage1_50pct":              "first profit target hit (+50%)",
            "stage2_break_even":         "remainder hit break-even stop",
            "stage2_stop_be":            "break-even stop triggered",
            "structural_stop_bar_high":  "structural stop (rejection level) hit",
            "manual":                    "manually closed by user",
            "panic":                     "emergency close triggered",
            "kill_lock_force_close":     "daily loss limit — force closed",
        }
        _reason_nice = next(
            (v for k, v in _reason_map.items() if reason and k in reason), reason or "exit signal"
        )
        _mode_tag = "[PAPER] " if paper else ""
        _emoji    = "🟢" if pnl >= 0 else "🔴"
        log_event(
            "INFO", "trading_logic",
            f"{_emoji} {_mode_tag}EXIT — Sold {_ticker_close} {_opt_close} "
            f"@ ${fill_price:.2f} (trigger ${exit_price:.2f}, entry ${_entry_px:.2f}). "
            f"P&L: {_pnl_sign}${pnl:.2f}. Reason: {_reason_nice}.",
        )
    except Exception:
        pass

    if pnl > 0:
        try:
            reserved = record_sweep(pnl, trade["id"])
            LIVE_STATE["last_tax_sweep"] = reserved
        except Exception as e:
            logger.error("Tax sweep failed: %s", e)

    try:
        _risk.record_pnl(pnl, account_balance=LIVE_STATE["account_balance"])
    except DailyLossLimitReached:
        raise

    LIVE_STATE["session_pnl"] = sum(
        t.get("realized_pnl", 0) for t in
        __import__("database").get_all_trades(limit=100)
        if t.get("exit_time", "")[:10] == date.today().isoformat()
    )
    closed_utc = _now_et()   # tz-aware ET
    # Determine what option type this trade was so we can compute the flip direction
    _closed_opt_type = trade.get("option_type", "")  # "call" or "put"
    _closed_direction = "bullish" if _closed_opt_type == "call" else "bearish"

    # ── Clear this position's per-trade state (NEW — MAX_CONCURRENT_POSITIONS) ─
    # Only THIS trade's slot is removed — if another position is still open,
    # its peak/stage/stop tracking in LIVE_STATE["positions"] is untouched.
    LIVE_STATE["positions"].pop(trade["id"], None)

    # Re-read open trades from the DB now that this one is closed. If another
    # position is still open, status stays "in_trade" so _tick() keeps
    # managing it; only go back to "scanning" once ALL positions are closed.
    _remaining_open               = get_open_trades()
    LIVE_STATE["open_trades"]      = _remaining_open
    LIVE_STATE["open_trade"]       = _remaining_open[0] if _remaining_open else None
    LIVE_STATE["status"]           = "in_trade" if _remaining_open else "scanning"
    LIVE_STATE["last_direction"]        = _closed_direction
    LIVE_STATE["last_trade_closed_time"]= closed_utc.isoformat()

    # FIX 2026-06-22 (direct request): the per-ticker session-long loss
    # cooldown (old "Fix 1") is removed. The user wants exactly one cooldown
    # active at a time — the win cooldown below when the daily loss cap
    # hasn't been hit, and the existing daily kill-lock (DAILY_LOSS_HARD_CAP_PCT
    # in risk.py, see check_kill_lock()) once it has. No code runs here for a
    # losing close anymore.
    # ⚠️ Known risk being accepted: this guard's original purpose was
    # specifically to stop the bot re-entering the SAME losing ticker
    # repeatedly in one session — it existed because of a real incident
    # (CRM entered 20× in one day, IWM 5× in a row on 2026-06-12). Removing
    # it means that pattern can recur on any day the daily loss cap isn't
    # hit; the per-entry quality gates (RVOL, R:R, spread, ATR floor) are the
    # only remaining defense against it.
    _closed_ticker = trade.get("ticker", "")
    if pnl > 0:
        # Post-win cooling period: block same-ticker re-entry for 10 minutes.
        # Prevents chasing back in immediately after a win (e.g. AAPL +$22 at
        # 10:43:37 → AAPL -$45 at 10:43:49 on 2026-06-18).
        if _closed_ticker:
            _WIN_COOLDOWN_MIN = 10
            _win_expires = _now_et() + timedelta(minutes=_WIN_COOLDOWN_MIN)
            LIVE_STATE.setdefault("ticker_win_cooldown", {})[_closed_ticker] = _win_expires
            log_event("INFO", "trading_logic",
                      f"⏱ [{_closed_ticker}] Post-win cooldown set for {_WIN_COOLDOWN_MIN} min "
                      f"(pnl=${pnl:+.2f}). No re-entry until "
                      f"{_win_expires.strftime('%H:%M')} ET.")

    # Remove this trade's entry from the bot_state.json bridge file so the
    # dashboard's "open_positions" list doesn't show a stale closed position.
    try:
        import json as _json_cl
        _state_path_cl = __import__("pathlib").Path(__file__).resolve().parent / "bot_state.json"
        if _state_path_cl.exists():
            with open(_state_path_cl) as _f:
                _existing_cl = _json_cl.load(_f)
            _open_positions_cl = _existing_cl.get("open_positions") or {}
            _open_positions_cl.pop(str(trade["id"]), None)
            _existing_cl["open_positions"] = _open_positions_cl
            with open(_state_path_cl, "w") as _f:
                _json_cl.dump(_existing_cl, _f)
    except Exception:
        pass
    # orb_triggered stays True — flip logic below may arm one re-entry exception

    # ── Flip-trade arming ─────────────────────────────────────────────────────
    # Arm ONLY when the initial 30% hard stop fires ("dynamic_stop_30pct").
    # No 15-minute cooldown — the flip is evaluated on the very next tick after
    # the stop is hit so the bot can immediately enter the opposite ORB extreme.
    #
    # Tightened stops (dynamic_stop_25pct / dynamic_stop_20pct), break-even exits,
    # time-box exits, and manual closes do NOT arm the flip — those are orderly
    # trade management events, not directional reversals.
    _is_hard_stop         = reason == "dynamic_stop_30pct"
    _flip_setting_enabled = bool(get_settings().get("flip_trading_enabled", True))
    if _is_hard_stop and _flip_setting_enabled:
        _flip_dir = "bearish" if _closed_direction == "bullish" else "bullish"
        _closed_ticker = trade.get("ticker", "")
        LIVE_STATE["flip_eligible"]  = True
        LIVE_STATE["flip_direction"] = _flip_dir
        LIVE_STATE["flip_ticker"]    = _closed_ticker  # scope flip to THIS ticker only
        logger.info(
            "flip_armed",
            extra={
                "event":           "flip_armed",
                "stopped_direction": _closed_direction,
                "flip_direction":  _flip_dir,
                "stop_reason":     reason,
                "trade_id":        trade["id"],
            },
        )
        log_event(
            "INFO", "trading_logic",
            f"🟡 Flip armed — previous {_closed_direction} trade stopped out. "
            f"Watching for a {_flip_dir} breakout to re-enter with the trend reversal.",
        )
    else:
        # Non-stop-loss close OR flip disabled in settings: clear any stale flip state
        LIVE_STATE["flip_eligible"]  = False
        LIVE_STATE["flip_direction"] = None
        LIVE_STATE["flip_ticker"]    = None

    _trade_log.info(
        "trade_closed",
        extra={
            "event":                   "trade_closed",
            # ── Mandatory 4-field audit signature ─────────────────────────
            "Trade_ID":                trade["id"],
            "Risk_Tier_Used":          _tier_label,   # resolved at top of _close_position
            "R_R_Ratio":               "n/a",        # computed on entry, not exit
            "Entry_Volume_Multiplier": "n/a",        # logged on entry
            # ── Close context ──────────────────────────────────────────────
            "exit_price":   round(exit_price, 4),
            "realized_pnl": round(pnl, 2),
            "exit_reason":  reason,
            "flip_armed":   _is_hard_stop and _flip_setting_enabled,
        },
    )
    # Clear per-trade context binding
    if hasattr(_trade_log, "clear_context"):
        _trade_log.clear_context()
    _trade_log = logger


# ── Manual controls ────────────────────────────────────────────────────────────

def close_trade_by_id(trade_id: int) -> dict:
    """
    NEW (2026-06-15 — Trade Journal per-row "Close Position" button).

    Close ONE specific open trade by its database id, without touching any
    other open positions. This is the per-row counterpart to
    manual_close_position() (which closes everything that's open).

    Used for both normal bot-opened trades AND the "recovered/untracked"
    rows that were inserted directly into the journal after being found as
    ghost positions at Alpaca (strategy_id == "RECOVERED_UNTRACKED") — those
    rows never had a corresponding Alpaca order placed by this bot, so we
    close them at the broker via close_position() (DELETE /v2/positions/{symbol}),
    which liquidates whatever Alpaca is actually holding for that symbol,
    rather than place_option_order() (which assumes this bot opened the
    position and would try to "sell" a position it has no record of placing).

    Returns a small status dict for the dashboard to display:
        {"ok": bool, "message": str, "pnl": float | None}
    """
    alpaca, tradier = get_clients()

    # Find the trade among currently-open trades. Re-reading from the DB
    # (rather than trusting LIVE_STATE) ensures we always act on the
    # latest persisted state, even right after a restart.
    trade = next((t for t in get_open_trades() if t["id"] == trade_id), None)
    if trade is None:
        msg = f"Trade #{trade_id} is not currently open — nothing to close."
        logger.warning("close_trade_by_id: %s", msg)
        return {"ok": False, "message": msg, "pnl": None}

    # ── Get a live price for the exit record ────────────────────────────────
    try:
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote and quote.get("mid", 0) > 0:
            exit_price = quote["mid"]
            logger.info("close_trade_by_id [trade %s]: live mid price = $%.4f",
                         trade_id, exit_price)
        else:
            exit_price = trade["entry_price"]
            logger.warning("close_trade_by_id [trade %s]: could not fetch live "
                            "price — using entry price as exit price", trade_id)
    except Exception as e:
        exit_price = trade["entry_price"]
        logger.error("close_trade_by_id [trade %s]: quote fetch failed (%s) — "
                      "using entry price as exit price", trade_id, e)

    # ── Liquidate at the broker ──────────────────────────────────────────────
    # close_position() hits DELETE /v2/positions/{symbol} for this symbol only
    # — it does not touch any other open positions at Alpaca.
    closed_at_broker = False
    try:
        closed_at_broker = alpaca.close_position(trade["contract_symbol"])
    except Exception as e:
        logger.error("close_trade_by_id [trade %s]: broker close_position raised %s",
                      trade_id, e)

    if not closed_at_broker:
        msg = (f"Could not close {trade['contract_symbol']} at the broker — "
               f"the journal entry was NOT marked closed. Check the audit log "
               f"and try again.")
        log_event("ERROR", "trading_logic",
                  f"🔴 Trade Journal close failed for trade #{trade_id} "
                  f"({trade['contract_symbol']}) — position left open.")
        return {"ok": False, "message": msg, "pnl": None}

    # ── Update the database row ──────────────────────────────────────────────
    try:
        pnl = close_trade(
            trade_id    = trade["id"],
            exit_price  = exit_price,
            exit_time   = _now_et(),   # tz-aware ET
            exit_reason = "manual_journal",
        )
    except Exception as e:
        logger.error("close_trade_by_id [trade %s]: close_trade() DB update "
                      "failed after broker close succeeded — manual DB fix "
                      "may be needed (%s)", trade_id, e)
        return {
            "ok": False,
            "message": (f"Closed {trade['contract_symbol']} at the broker, but "
                         f"FAILED to update the journal record (#{trade_id}). "
                         f"The position is closed at Alpaca — please refresh "
                         f"and check the journal manually."),
            "pnl": None,
        }

    log_event(
        "INFO", "trading_logic",
        f"🟡 Trade Journal — manually closed {trade.get('ticker', '?')} "
        f"{trade.get('option_type', 'option').upper()} (trade #{trade_id}) "
        f"@ ${exit_price:.2f}. P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}.",
    )

    # ── Clear this trade's per-position state (mirrors _close_position) ──────
    LIVE_STATE["positions"].pop(trade_id, None)
    _remaining_open            = get_open_trades()
    LIVE_STATE["open_trades"]  = _remaining_open
    LIVE_STATE["open_trade"]   = _remaining_open[0] if _remaining_open else None
    LIVE_STATE["status"]       = "in_trade" if _remaining_open else "scanning"

    # ── Remove this trade's entry from bot_state.json's open_positions ───────
    try:
        import json as _json_cb
        _state_path_cb = __import__("pathlib").Path(__file__).resolve().parent / "bot_state.json"
        if _state_path_cb.exists():
            with open(_state_path_cb) as _f:
                _existing_cb = _json_cb.load(_f)
            _open_positions_cb = _existing_cb.get("open_positions") or {}
            _open_positions_cb.pop(str(trade_id), None)
            _existing_cb["open_positions"] = _open_positions_cb
            with open(_state_path_cb, "w") as _f:
                _json_cb.dump(_existing_cb, _f)
    except Exception:
        pass

    return {
        "ok": True,
        "message": (f"Closed {trade.get('ticker', '?')} {trade.get('option_type','')} "
                     f"@ ${exit_price:.2f}. P&L: {'+' if pnl >= 0 else ''}${pnl:.2f}."),
        "pnl": pnl,
    }


def manual_close_position() -> None:
    """
    FIX M12: Fetch live quote for exit price instead of entry * 0.95.

    UPDATED (MAX_CONCURRENT_POSITIONS): the dashboard's "Close Position" button
    closes whatever is open. With up to 2 concurrent positions now possible,
    this closes ALL currently-open trades (one at a time, each with its own
    live quote) rather than just the single most-recent one — so the button
    still does what a user expects ("close my position(s) now").
    """
    alpaca, tradier = get_clients()
    trades = get_open_trades()
    if not trades:
        logger.info("Manual close: no open position")
        return

    for trade in trades:
        # Try to get live price
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote and quote.get("mid", 0) > 0:
            exit_price = quote["mid"]
            logger.info("Manual close [trade %s]: live mid price = $%.4f", trade["id"], exit_price)
        else:
            # Fallback: use last known price from live state (better than entry*0.95)
            exit_price = trade["entry_price"]
            logger.warning("Manual close [trade %s]: could not fetch live price — using entry price", trade["id"])

        _close_position(alpaca, trade, exit_price, reason="manual")


def panic_close_all() -> None:
    """
    UPDATED (MAX_CONCURRENT_POSITIONS): alpaca.close_all_positions() already
    flattens everything at the broker regardless of how many positions are
    open. The DB side previously only closed ONE trade via get_open_trade() —
    with up to 2 concurrent positions, loop over get_open_trades() so every
    open DB row gets marked closed too.
    """
    alpaca, _ = get_clients()
    alpaca.close_all_positions()
    trades = get_open_trades()
    for trade in trades:
        try:
            quote = __import__("broker").TradierClient().get_option_quote(trade["contract_symbol"])
            exit_px = quote["mid"] if quote else trade["entry_price"]
        except Exception:
            exit_px = trade["entry_price"]
        close_trade(trade["id"], exit_price=exit_px,
                    exit_time=_now_et(), exit_reason="panic")
    LIVE_STATE["status"] = "halted"
    log_event("WARNING", "trading_logic",
              "🔴 Emergency close triggered — all positions have been closed.")


def _panic_close_all_positions(alpaca: AlpacaClient, tradier: TradierClient) -> None:
    """
    Internal variant called by the kill-lock handler in run_trading_loop.
    Closes all broker positions and marks any open DB trade(s) as force-closed.

    UPDATED (MAX_CONCURRENT_POSITIONS): loop over get_open_trades() instead of
    a single get_open_trade() — the kill lock must force-close BOTH legs if 2
    positions happen to be open when the daily loss cap fires.
    """
    try:
        alpaca.close_all_positions()
    except Exception as ex:
        logger.error("kill_lock_close_all failed: %s", ex)
    trades = get_open_trades()
    for trade in trades:
        try:
            quote   = tradier.get_option_quote(trade["contract_symbol"])
            exit_px = quote["mid"] if quote else trade["entry_price"]
        except Exception:
            exit_px = trade["entry_price"]
        close_trade(
            trade["id"],
            exit_price  = exit_px,
            exit_time   = _now_et(),   # tz-aware ET
            exit_reason = "kill_lock_force_close",
        )
    LIVE_STATE["status"]       = "kill_locked"
    LIVE_STATE["open_trade"]   = None
    LIVE_STATE["open_trades"]  = []
    LIVE_STATE["positions"]    = {}
    log_event("CRITICAL", "trading_logic",
              "🔴 Daily loss limit hit — all positions closed. "
              "Trading is frozen for 24 hours to protect your account.")


def stop_loop() -> None:
    _stop_event.set()
    LIVE_STATE["running"] = False   # dashboard picks this up immediately
    # Also persist to bot_state.json so the topbar (which reads the file,
    # not LIVE_STATE) reflects the stopped state without waiting for the
    # next tick to overwrite it.
    try:
        _state_path = Path(__file__).resolve().parent / "bot_state.json"
        if _state_path.exists():
            import json as _json
            _st = _json.loads(_state_path.read_text())
            _st["running"] = False
            _state_path.write_text(_json.dumps(_st, indent=2, default=str))
    except Exception as _se:
        logger.warning("stop_loop: failed to update bot_state.json: %s", _se)


def _sleep_until_next_day() -> None:
    # _ET_TZ and _now_et() imported at module level — no local import needed
    now_et    = _now_et()
    next_open = now_et.replace(hour=9, minute=31, second=0, microsecond=0)
    next_open += timedelta(days=1)
    while next_open.weekday() >= 5:
        next_open += timedelta(days=1)
    secs = max(60, (next_open - _now_et()).total_seconds())
    logger.info("Sleeping %.1f hours until next market open", secs/3600)
    time.sleep(secs)