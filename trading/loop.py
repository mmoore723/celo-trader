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
)

logger = logging.getLogger("celo_trader.trading_logic")


def run_trading_loop(poll_interval: int = 10) -> None:
    """
    Singleton-guarded entry point.  Only ONE trading loop may run at a time.
    """
    if not _bot_loop_lock.acquire(blocking=False):
        logger.warning(
            "run_trading_loop called while another loop is already running — "
            "refusing to start a second concurrent loop."
        )
        from database import log_event
        log_event(
            "WARNING", "trading_logic",
            "⚠️ Start Bot pressed while a loop is already running — ignored. "
            "Press Stop first, wait a few seconds, then Start again."
        )
        return
    try:
        _stop_event.clear()
        _run_trading_loop_inner(poll_interval)
    finally:
        _bot_loop_lock.release()


def _run_trading_loop_inner(poll_interval: int = 10) -> None:
    """Inner body of the trading loop — called exclusively from run_trading_loop()."""
    # _risk lives in entry.py (because _tick() uses `global _risk` there).
    # We set it through the module object so _tick() sees the new instance.
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

    # FIX: seed LIVE_STATE["account_balance"] immediately before the first tick.
    LIVE_STATE["account_balance"] = balance

    # FIX: seed LIVE_STATE["session_pnl"] from DB at startup to survive restarts.
    # Use (val or 0) guards so None values from nullable DB columns don't crash
    # the sum (t.get("exit_time", "") returns None when the column is NULL).
    try:
        LIVE_STATE["session_pnl"] = sum(
            (t.get("realized_pnl") or 0) for t in get_all_trades(limit=100)
            if (t.get("exit_time") or "")[:10] == date.today().isoformat()
        )
    except Exception as e:
        logger.error("Could not recompute session_pnl from DB at startup: %s", e)
        LIVE_STATE["session_pnl"] = 0.0

    _em._risk = RiskManager(account_balance=balance)
    logger.info(
        "bot_started",
        extra={"event": "bot_started", "account_balance": round(balance, 2)},
    )
    log_event("INFO", "trading_logic", f"🟢 Bot started. Account balance: ${balance:.2f}")
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
                # Today's scan already ran — restore it
                _restored_wl = _du["universe"]
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
    except Exception:
        pass
    LIVE_STATE["current_option_price"]      = _prev_opt_px
    LIVE_STATE["current_option_price_time"] = _prev_opt_px_time
    try:
        _state_path_start = _BOT_ROOT / "bot_state.json"
        json.dump({
            "running":              True,
            "auto_start_disabled":  False,   # clear explicit-stop flag on fresh start
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

    while not _stop_event.is_set():
        try:
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
                if _stop_event.wait(timeout=300):
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
            _stop_event.wait(timeout=30)

        # Smart sleep: poll_interval inside trading window, 60s outside.
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
            _stop_event.wait(timeout=poll_interval if _in_window else 60)
        except Exception as _sleep_err:
            logger.warning("Smart sleep error (non-fatal): %s", _sleep_err)
            _stop_event.wait(timeout=poll_interval)

    # Only log "stopped" when the stop was intentional (_stop_event was set).
    # Unexpected exits (exceptions escaping the loop body) are already logged
    # as errors above — an extra "Trading loop stopped" would be misleading.
    if _stop_event.is_set():
        logger.info("Trading loop stopped")
    else:
        logger.warning("Trading loop exited unexpectedly — will be restarted by auto-start")


def stop_loop() -> None:
    """Signal the loop to exit and persist the stopped state to bot_state.json."""
    _stop_event.set()
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
