"""
trading/loop.py — Main trading loop lifecycle.

Functions:
  run_trading_loop        — public entry point (singleton-guarded)
  _run_trading_loop_inner — inner body
  stop_loop               — signal the loop to exit
  _sleep_until_next_day   — sleep until next 9:31 ET open
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from trading.state import (
    LIVE_STATE, _now_et, _stop_event, _bot_loop_lock, _BOT_ROOT,
    _get_stop_event, _get_lock, get_user_state,
)

logger = logging.getLogger("celo_trader.trading_logic")


def run_trading_loop(user_id: str = "admin", poll_interval: int = 10) -> None:
    """
    Singleton-guarded entry point.  One trading loop per user at a time.
    Called via ctx.run() from bot.py so the ContextVar (user identity) is
    already set and propagates into all downstream helpers.
    """
    _lock  = _get_lock(user_id)
    _stop  = _get_stop_event(user_id)
    if not _lock.acquire(blocking=False):
        logger.warning(
            "run_trading_loop called while loop for user %s is already running", user_id
        )
        from database import log_event
        log_event(
            "WARNING", "trading_logic",
            "⚠️ Start Bot pressed while a loop is already running — ignored. "
            "Press Stop first, wait a few seconds, then Start again."
        )
        return
    try:
        _stop.clear()
        _run_trading_loop_inner(user_id=user_id, poll_interval=poll_interval)
    finally:
        _lock.release()


def _run_trading_loop_inner(user_id: str = "admin", poll_interval: int = 10) -> None:
    """Inner body of the trading loop — called exclusively from run_trading_loop()."""
    import trading.entry as _em

    from broker import get_clients
    from config import get_settings, STARTING_CAPITAL, get_trading_windows as _gtw
    from database import init_db, log_event, get_all_trades
    from risk import RiskManager, DailyLossLimitReached
    from alerts import send_alert
    from scanner import run_scan, is_scan_window
    from trading.entry import _tick
    from trading.diagnostics import _check_ghost_positions
    from trading.controls import _panic_close_all_positions

    # Use this user's state dict instead of the global LIVE_STATE alias.
    # All code inside this function that previously used LIVE_STATE now uses
    # _US, which is the per-user dict from the USER_STATES registry.
    _US = get_user_state(user_id)

    # Resolve stop event for this user
    _stop = _get_stop_event(user_id)

    init_db()
    alpaca, tradier = get_clients()

    # Determine mode from settings (written by start_bot() before the loop starts).
    _settings   = get_settings()
    _is_paper   = _settings.get("paper_trading", True)
    _trade_mode = "paper" if _is_paper else "live"
    _US["mode"] = _trade_mode
    LIVE_STATE["mode"] = _trade_mode   # keep global alias in sync for admin user

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

    _US["account_balance"]  = balance
    LIVE_STATE["account_balance"] = balance

    # Day-start balance: persist per calendar date so mid-session bot restarts
    # don't overwrite the true opening value with the current (already-traded) balance.
    # Key: "day_start_YYYY-MM-DD" in settings — only written on first start of the day.
    from config import save_settings as _save_dsb
    import datetime as _dt_dsb
    _today_key = f"day_start_{_dt_dsb.date.today().isoformat()}"
    _saved_dsb = get_settings().get(_today_key)
    if _saved_dsb:
        # Bot restarted mid-session — use the balance saved at first start today
        day_start_balance = float(_saved_dsb)
    else:
        # First start of the day — lock in today's opening Alpaca equity
        day_start_balance = balance
        _save_dsb({_today_key: round(day_start_balance, 2)})
    _US["day_start_balance"]        = day_start_balance
    LIVE_STATE["day_start_balance"] = day_start_balance

    try:
        _US["session_pnl"] = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(limit=100, mode=_trade_mode)
            if (t.get("exit_time") or "")[:10] == date.today().isoformat()
        )
    except Exception as e:
        logger.error("Could not recompute session_pnl from DB at startup: %s", e)
        _US["session_pnl"] = 0.0
    LIVE_STATE["session_pnl"] = _US["session_pnl"]

    _em._risk = RiskManager(account_balance=balance)
    logger.info("bot_started", extra={"event": "bot_started", "account_balance": round(balance, 2)})
    log_event("INFO", "trading_logic", f"🟢 Bot started [{user_id}]. Account balance: ${balance:.2f}")
    _US["running"] = True
    LIVE_STATE["running"] = True

    # ── Startup reconciliation ────────────────────────────────────────────────
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

    # ── Watchlist restoration on mid-session restart ──────────────────────────
    # If the bot restarts after the 9:00–11:30 scan window, is_scan_window()
    # returns False and the scan block in the main loop never runs, leaving
    # scan_watchlist empty and _tick() with nothing to evaluate.
    # Fix: on startup, check daily_universe.json — if today's scan already ran,
    # restore it immediately so the bot can resume trading without a full rescan.
    if not LIVE_STATE.get("scan_watchlist"):
        try:
            from scanner import _read_daily_universe, _et_now as _scanner_et
            from config import get_settings as _get_s_wl
            _du = _read_daily_universe()
            _today_str = _scanner_et().strftime("%Y-%m-%d")
            if _du.get("date") == _today_str and _du.get("universe"):
                # Today's scan already ran — restore it, prepending settings
                # watchlist pins so user-pinned tickers (e.g. AMZN, TSLA) are
                # ALWAYS included even if they didn't rank in the morning scan.
                _pins_r = [
                    t.upper().strip()
                    for t in (_get_s_wl().get("watchlist") or [])
                    if t.strip()
                ]
                _restored_wl = list(dict.fromkeys(_pins_r + _du["universe"]))
                LIVE_STATE["scan_watchlist"]    = _restored_wl
                LIVE_STATE["scanner_ran_today"] = True
                LIVE_STATE["current_ticker"]    = _restored_wl[0]
                log_event("INFO", "scanner",
                          f"🔄 Restored today's scan watchlist after restart: "
                          f"{', '.join(_restored_wl)}")
            else:
                # No daily universe yet — seed from settings watchlist + anchors
                _pins = [t.upper().strip() for t in (_get_s_wl().get("watchlist") or []) if t.strip()]
                _seed = list(dict.fromkeys(_pins + ["SPY", "QQQ"]))[:10]
                LIVE_STATE["scan_watchlist"]    = _seed
                LIVE_STATE["scanner_ran_today"] = False   # force rescan when window opens
                LIVE_STATE["current_ticker"]    = _seed[0]
                log_event("INFO", "scanner",
                          f"🔄 No daily universe yet — seeding watchlist: {', '.join(_seed)}")
        except Exception as _wl_err:
            logger.warning("Watchlist restore failed: %s — using anchors", _wl_err)
            LIVE_STATE["scan_watchlist"]    = ["SPY", "QQQ"]
            LIVE_STATE["current_ticker"]    = "SPY"
            LIVE_STATE["scanner_ran_today"] = False

    # Write initial bot_state.json, carrying forward last-known option price.
    _prev_opt_px      = None
    _prev_opt_px_time = None
    try:
        _state_path_start = _BOT_ROOT / "bot_state.json"
        if _state_path_start.exists():
            with open(_state_path_start) as _f:
                _prev_state = json.load(_f)
            _prev_opt_px      = _prev_state.get("current_option_price")
            _prev_opt_px_time = _prev_state.get("current_option_price_time")
            # ── Carry forward today's signal history so restarts don't wipe the log ──
            # eval_log entries only have a time (HH:MM:SS), not a date, so we keep
            # them all (capped at 10) — stale entries are displaced by new ones quickly.
            _prev_eval = _prev_state.get("eval_log", [])
            if _prev_eval:
                LIVE_STATE["eval_log"] = _prev_eval
    except Exception:
        pass
    LIVE_STATE["current_option_price"]      = _prev_opt_px
    LIVE_STATE["current_option_price_time"] = _prev_opt_px_time
    try:
        _state_path_start = _BOT_ROOT / "bot_state.json"
        json.dump({
            "running":              True,
            "auto_start_disabled":  False,   # clear explicit-stop flag on fresh start
            "mode":                 _trade_mode,   # "paper" or "live" — shown in dashboard
            "account_balance":      float(balance),
            "session_pnl":          LIVE_STATE.get("session_pnl", 0.0),
            "status":               "starting",
            "current_ticker":       None,
            "last_signal":          None,
            "market_open":          False,
            "last_update":          time.strftime("%H:%M:%S"),
            "current_option_price":      _prev_opt_px,
            "current_option_price_time": _prev_opt_px_time,
        }, open(_state_path_start, "w"))
    except Exception:
        pass

    while not _stop.is_set():
        try:
            # ── After-hours deep sleep: 5:00 PM – 8:00 AM ET ─────────────────
            # No scan, no tick, no API calls. Wakes at 8:00 AM on the next
            # weekday. Sleeps in 5-minute chunks so Stop Bot still responds.
            _now_et_ah = _now_et()
            _hm_ah     = _now_et_ah.hour * 60 + _now_et_ah.minute
            _AFTER_HOURS = _hm_ah >= 17 * 60 or _hm_ah < 8 * 60

            if _AFTER_HOURS:
                # Compute next 8:00 AM ET, skipping weekends.
                _wake = _now_et_ah.replace(hour=8, minute=0, second=0, microsecond=0)
                if _now_et_ah >= _wake:
                    _wake += timedelta(days=1)
                while _wake.weekday() >= 5:          # 5=Sat, 6=Sun
                    _wake += timedelta(days=1)
                _secs_until_wake = max(60, (_wake - _now_et()).total_seconds())

                # Log once when we first enter after-hours.
                if not LIVE_STATE.get("_after_hours_sleeping"):
                    LIVE_STATE["_after_hours_sleeping"] = True
                    log_event(
                        "INFO", "trading_logic",
                        f"🌙 Markets closed — bot resting until 8:00 AM ET "
                        f"({_wake.strftime('%a %b %d')}). No API calls during this window.",
                    )

                # Sleep up to 5 min at a time so Stop Bot stays responsive.
                _stop_event.wait(timeout=min(300, _secs_until_wake))
                continue   # skip scan + _tick entirely

            # Waking up from after-hours — log once.
            if LIVE_STATE.get("_after_hours_sleeping"):
                LIVE_STATE["_after_hours_sleeping"] = False
                log_event("INFO", "trading_logic",
                          "🌅 Good morning — resuming pre-market watch.")

            # ── Daily scan ───────────────────────────────────────────────────
            # Run if: scan hasn't run today AND we're in the scan window.
            # Also run if scan_watchlist is empty regardless of time — this
            # catches the edge case where the restore above produced no results.
            _needs_scan = (
                not LIVE_STATE.get("scanner_ran_today") and is_scan_window()
            ) or not LIVE_STATE.get("scan_watchlist")
            if _needs_scan:
                try:
                    wl = run_scan(alpaca, max_tickers=10)
                    # Always prepend user's settings pins so tickers like XLE
                    # stay in the watchlist even if the scanner didn't rank them.
                    # dict.fromkeys preserves order and deduplicates.
                    try:
                        from config import get_settings as _get_scan_pins
                        _pins = [t.upper().strip() for t in (_get_scan_pins().get("watchlist") or []) if t.strip()]
                        wl = list(dict.fromkeys(_pins + wl))
                    except Exception:
                        pass
                    LIVE_STATE["scan_watchlist"] = wl
                    LIVE_STATE["scan_idx"]       = 0
                    if wl:
                        LIVE_STATE["current_ticker"] = wl[0]

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
                    LIVE_STATE["scanner_ran_today"] = False
                    LIVE_STATE["current_ticker"]    = "SPY"

            # ── Refresh account balance + recompute session P&L ─────────────
            # Balance is fetched from Alpaca once per batch cycle (every ~60s)
            # so the dashboard always shows current equity.
            # session_pnl is derived from real equity delta — not DB trade sums —
            # so it matches Alpaca's account value regardless of fill-price bugs.
            try:
                _acct_tick = alpaca.get_account()
                _bal_tick  = float(_acct_tick.get("equity", 0)) if _acct_tick else 0
                if _bal_tick > 0:
                    _US["account_balance"]         = _bal_tick
                    LIVE_STATE["account_balance"]  = _bal_tick
                    _dsb = LIVE_STATE.get("day_start_balance") or _bal_tick
                    _spnl = round(_bal_tick - _dsb, 2)
                    _US["session_pnl"]             = _spnl
                    LIVE_STATE["session_pnl"]      = _spnl
                    # Persist so the WebSocket + bot_state.json stay in sync
                    from config import save_settings as _save_bal
                    _save_bal({"last_known_balance": round(_bal_tick, 2)})
            except Exception as _bal_err:
                logger.debug("Balance refresh failed (non-fatal): %s", _bal_err)

            # ── Batch-evaluate ALL watchlist tickers once per bar ────────────
            # Old design: one ticker per 10-second tick.  With 10 tickers the
            # cycle took ~100 s, so each ticker was only seen every 1.5 bars.
            # New design: run _tick() for each ticker in one pass, then sleep
            # to the next 60-second bar boundary.  Every ticker now gets one
            # evaluation per new 1-minute candle — no missed bars, no stale
            # re-evaluations, ~40% fewer redundant API calls.
            _wl_batch = LIVE_STATE.get("scan_watchlist") or ["SPY", "QQQ"]
            for _bi in range(len(_wl_batch)):
                if _stop.is_set():
                    break
                _tick(alpaca, tradier)

        except DailyLossLimitReached as e:
            LIVE_STATE["status"] = "kill_locked"
            send_alert("DAILY LOSS LIMIT — KILL LOCK ACTIVE", str(e))
            try:
                _panic_close_all_positions(alpaca, tradier)
            except Exception as _ce:
                logger.error("Panic close on kill lock failed: %s", _ce)
            logger.warning("kill_lock_sleep: trading halted for 24h")
            for _ in range(288):   # 288 × 5 min = 24 h
                # _stop_event.wait() returns immediately when Stop Bot is pressed
                if _stop.wait(timeout=300):
                    break
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.exception("Unexpected error in trading loop: %s", e)
            log_event("ERROR", "trading_logic",
                      f"🔴 Unexpected error in trading loop: {type(e).__name__}. "
                      f"Bot will retry on next tick. ({e})")
            send_alert("CRITICAL ERROR", str(e))
            LIVE_STATE["status"]      = "error"
            LIVE_STATE["last_update"] = _now_et().isoformat()
            try:
                json.dump({
                    "running":    True,
                    "status":     "error",
                    "last_error": str(e)[:200],
                    "last_update": LIVE_STATE["last_update"],
                    "account_balance": LIVE_STATE.get("account_balance", 0),
                    "market_open": LIVE_STATE.get("market_open", False),
                }, open(_BOT_ROOT / "bot_state.json", "w"))
            except Exception:
                pass
            _stop.wait(timeout=30)

        # ── Sleep until the next 60-second bar boundary ───────────────────────
        # Inside the trading window: sleep to the start of the next 1-minute
        # candle so every tick sees fresh bars.  Floor at 5 s so a slow pass
        # never blocks for a whole minute when already near the boundary.
        # Outside the trading window: sleep 60 s (rate-limit API when idle).
        # Wrapped in try/except — any exception here used to silently exit
        # the while loop (it was outside the inner try/except), causing the
        # "Trading loop stopped" log with no error message.
        try:
            _now_et_sl = _now_et()
            _hm        = _now_et_sl.hour * 60 + _now_et_sl.minute
            _balance   = LIVE_STATE.get("account_balance", 0)
            _windows   = _gtw(_balance)
            _in_window = any(
                int(s.split(":")[0]) * 60 + int(s.split(":")[1]) <= _hm <=
                int(e.split(":")[0]) * 60 + int(e.split(":")[1])
                for s, e in _windows
            )
            if _in_window:
                # Sleep to next minute boundary (new bar = new data)
                _secs_into = _now_et_sl.second + _now_et_sl.microsecond / 1_000_000
                _secs_wait = max(5.0, 60.0 - _secs_into)
                _stop.wait(timeout=_secs_wait)
            else:
                _stop.wait(timeout=60)
        except Exception as _sleep_err:
            logger.warning("Smart sleep error (non-fatal): %s", _sleep_err)
            _stop_event.wait(timeout=poll_interval)

    # Only log "stopped" when the stop was intentional (_stop_event was set).
    # Unexpected exits (exceptions escaping the loop body) are already logged
    # as errors above — an extra "Trading loop stopped" would be misleading.
    if _stop.is_set():
        logger.info("Trading loop stopped")
    else:
        logger.warning("Trading loop exited unexpectedly — will be restarted by auto-start")


def stop_loop(user_id: str = "admin") -> None:
    """Signal the loop for a given user to exit."""
    _get_stop_event(user_id).set()
    get_user_state(user_id)["running"] = False
    LIVE_STATE["running"] = False
    # Log to the database so the THINKING panel shows confirmation that the bot
    # actually received the stop signal (not just a network disconnect).
    try:
        from database import log_event
        log_event("INFO", "trading_logic", "🔴 Bot stopped.")
    except Exception:
        pass
    try:
        _state_path = _BOT_ROOT / "bot_state.json"
        if _state_path.exists():
            _st = json.loads(_state_path.read_text())
            _st["running"] = False
            # auto_start_disabled = True tells the service-restart auto-start
            # logic NOT to resume the bot — the user explicitly pressed Stop.
            _st["auto_start_disabled"] = True
            _state_path.write_text(json.dumps(_st, indent=2, default=str))
    except Exception as _se:
        logger.warning("stop_loop: failed to update bot_state.json: %s", _se)


def _sleep_until_next_day() -> None:
    """Sleep until 9:31 ET on the next trading day."""
    now_et    = _now_et()
    next_open = now_et.replace(hour=9, minute=31, second=0, microsecond=0)
    next_open += timedelta(days=1)
    while next_open.weekday() >= 5:
        next_open += timedelta(days=1)
    secs = max(60, (next_open - _now_et()).total_seconds())
    logger.info("Sleeping %.1f hours until next market open", secs / 3600)
    time.sleep(secs)
