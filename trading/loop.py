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
    _now_et,
    _get_stop_event, _get_lock, get_user_state, set_user_risk,
)
from config import get_bot_state_path

logger = logging.getLogger("celo_trader.trading_logic")


def run_trading_loop(user_id: str = "admin", poll_interval: int = 10) -> None:
    """
    Singleton-guarded entry point.  One trading loop per user at a time.

    api/routes/bot.py::start_bot() spawns this via contextvars.copy_context()
    so the auth ContextVar (user identity) is already correct in this thread
    before this function even runs. BUT this function is also called from
    api/main.py's service-restart auto-resume path via a plain
    threading.Thread (no request in flight there to copy a context from) —
    so we explicitly (re)establish the ContextVar identity here ourselves,
    rather than assuming the caller already did it. This is what every
    downstream `get_user_state()` / `get_user_risk()` / `get_user_trade_log()`
    call (with no explicit user_id) resolves against, so getting this right
    is what makes the whole per-user state fix actually correct — without it,
    a bot resumed via the auto-start path would silently run against admin's
    state/risk/logger regardless of which user's loop this is.
    """
    try:
        from auth.context import set_current_user
        set_current_user(user_id, username=user_id, is_admin=False)
    except Exception as _ctx_err:
        logger.warning("run_trading_loop: could not set user context: %s", _ctx_err)

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


def _run_nightly_strategy_audit_once(alpaca) -> None:
    """
    Trigger the built-in strategy health audit (strategy_health/runner.py)
    once per calendar day, right as the bot enters after-hours sleep.
    Runs in a background thread so a slow audit never delays the deep-sleep
    loop or blocks Stop Bot from responding. Deduped via a saved settings
    key so a mid-evening bot restart doesn't re-run the same day's audit.
    """
    import threading
    from config import get_settings, save_settings

    today_str = date.today().isoformat()
    if get_settings().get("last_strategy_audit_date") == today_str:
        return   # already ran today

    def _worker() -> None:
        try:
            from strategy_health.runner import run_daily_audit
            from database import log_event as _le
            run_daily_audit(alpaca)
            save_settings({"last_strategy_audit_date": today_str})
            _le("INFO", "trading_logic", "📊 Nightly strategy health audit complete — see Strategy Health page.")
        except Exception as exc:
            logger.warning("Nightly strategy audit failed (non-fatal): %s", exc)

    threading.Thread(target=_worker, daemon=True, name="strategy-health-audit").start()


def _run_trading_loop_inner(user_id: str = "admin", poll_interval: int = 10) -> None:
    """Inner body of the trading loop — called exclusively from run_trading_loop()."""
    from broker import get_clients
    from config import get_settings, STARTING_CAPITAL, get_trading_windows as _gtw
    from database import init_db, log_event, get_all_trades
    from risk import RiskManager, DailyLossLimitReached
    from alerts import send_alert
    from scanner import run_scan, is_scan_window
    from trading.entry import _tick
    from trading.diagnostics import _check_ghost_positions
    from trading.controls import _panic_close_all_positions

    # This user's own state dict — see trading/state.py::get_user_state.
    # FIX: this function used to ALSO mirror every write into the global
    # LIVE_STATE alias ("to keep it in sync for the admin user") — meaning a
    # non-admin user's loop silently overwrote the admin dashboard's balance,
    # P&L, watchlist, and status on every tick. Nothing else in the codebase
    # reads that alias anymore (entry.py/position_manager.py/diagnostics.py/
    # annotations.py all resolve get_user_state() fresh per-call now), so the
    # dual-write is gone — this loop only ever touches its own user's state.
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

    _US["account_balance"] = balance

    # Day-start balance: persist per calendar date so mid-session bot restarts
    # don't overwrite the true opening value with the current (already-traded) balance.
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
    _US["day_start_balance"] = day_start_balance

    try:
        _US["session_pnl"] = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(limit=100, mode=_trade_mode)
            if (t.get("exit_time") or "")[:10] == date.today().isoformat()
        )
    except Exception as e:
        logger.error("Could not recompute session_pnl from DB at startup: %s", e)
        _US["session_pnl"] = 0.0

    # FIX: was `_em._risk = RiskManager(...)` — a module-level global on
    # trading.entry shared by every user's thread (see trading/state.py's
    # get_user_risk/set_user_risk docstring for the full explanation).
    set_user_risk(RiskManager(account_balance=balance), user_id)
    logger.info("bot_started", extra={"event": "bot_started", "account_balance": round(balance, 2)})
    log_event("INFO", "trading_logic", f"🟢 Bot started [{user_id}]. Account balance: ${balance:.2f}")
    _US["running"] = True

    # ── Startup reconciliation ────────────────────────────────────────────────
    try:
        _startup_ghost = _check_ghost_positions(alpaca)
        _US["ghost_position_alert"] = _startup_ghost
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
    if not _US.get("scan_watchlist"):
        try:
            from scanner import _read_daily_universe, _et_now as _scanner_et
            from config import get_settings as _get_s_wl
            _du = _read_daily_universe()
            _today_str = _scanner_et().strftime("%Y-%m-%d")
            if _du.get("date") == _today_str and _du.get("universe"):
                # Today's scan already ran — restore it, prepending settings
                # watchlist pins so user-pinned tickers (e.g. AMZN, TSLA) are
                _pins_r = [
                    t.upper().strip()
                    for t in (_get_s_wl().get("watchlist") or [])
                    if t.strip()
                ]
                _restored_wl = list(dict.fromkeys(_pins_r + _du["universe"]))
                _US["scan_watchlist"]    = _restored_wl
                _US["scanner_ran_today"] = True
                _US["current_ticker"]    = _restored_wl[0]
                log_event("INFO", "scanner",
                          f"🔄 Restored today's scan watchlist after restart: "
                          f"{', '.join(_restored_wl)}")
            else:
                # No daily universe yet — seed from settings watchlist + anchors
                _pins = [t.upper().strip() for t in (_get_s_wl().get("watchlist") or []) if t.strip()]
                _seed = list(dict.fromkeys(_pins + ["SPY", "QQQ"]))[:10]
                _US["scan_watchlist"]    = _seed
                _US["scanner_ran_today"] = False   # force rescan when window opens
                _US["current_ticker"]    = _seed[0]
                log_event("INFO", "scanner",
                          f"🔄 No daily universe yet — seeding watchlist: {', '.join(_seed)}")
        except Exception as _wl_err:
            logger.warning("Watchlist restore failed: %s — using anchors", _wl_err)
            _US["scan_watchlist"]    = ["SPY", "QQQ"]
            _US["current_ticker"]    = "SPY"
            _US["scanner_ran_today"] = False

    # Write initial bot_state.json, carrying forward last-known option price.
    _prev_opt_px      = None
    _prev_opt_px_time = None
    try:
        _state_path_start = get_bot_state_path(user_id)
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
                _US["eval_log"] = _prev_eval
    except Exception:
        pass
    _US["current_option_price"]      = _prev_opt_px
    _US["current_option_price_time"] = _prev_opt_px_time
    try:
        _state_path_start = get_bot_state_path(user_id)
        json.dump({
            "running":              True,
            "auto_start_disabled":  False,   # clear explicit-stop flag on fresh start
            "mode":                 _trade_mode,   # "paper" or "live" — shown in dashboard
            "account_balance":      float(balance),
            "session_pnl":          _US.get("session_pnl", 0.0),
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
                if not _US.get("_after_hours_sleeping"):
                    _US["_after_hours_sleeping"] = True
                    log_event(
                        "INFO", "trading_logic",
                        f"🌙 Markets closed — bot resting until 8:00 AM ET "
                        f"({_wake.strftime('%a %b %d')}). No API calls during this window.",
                    )
                    _run_nightly_strategy_audit_once(alpaca)

                # Sleep up to 5 min at a time so Stop Bot stays responsive.
                # FIX: this used to wait on the module-level admin-only
                # _stop_event instead of this user's own _stop — a non-admin
                # user's Stop button wouldn't wake their thread during
                # after-hours sleep, and admin's Stop would wrongly wake
                # everyone else's.
                _stop.wait(timeout=min(300, _secs_until_wake))
                continue   # skip scan + _tick entirely

            # Waking up from after-hours — log once.
            if _US.get("_after_hours_sleeping"):
                _US["_after_hours_sleeping"] = False
                log_event("INFO", "trading_logic",
                          "🌅 Good morning — resuming pre-market watch.")

            # ── Daily scan ───────────────────────────────────────────────────
            # Run if: scan hasn't run today AND we're in the scan window.
            # Also run if scan_watchlist is empty regardless of time — this
            _needs_scan = (
                not _US.get("scanner_ran_today") and is_scan_window()
            ) or not _US.get("scan_watchlist")
            if _needs_scan:
                try:
                    wl = run_scan(alpaca, max_tickers=10)
                    # Always prepend user's settings pins so tickers like XLE
                    # stay in the watchlist even if the scanner didn't rank them.
                    try:
                        from config import get_settings as _get_scan_pins
                        _pins = [t.upper().strip() for t in (_get_scan_pins().get("watchlist") or []) if t.strip()]
                        wl = list(dict.fromkeys(_pins + wl))
                    except Exception:
                        pass
                    _US["scan_watchlist"] = wl
                    _US["scan_idx"]       = 0
                    if wl:
                        _US["current_ticker"] = wl[0]

                    from scanner import _read_daily_universe, _et_now as _scanner_et_now
                    _du = _read_daily_universe()
                    _full_scan_ran = (_du.get("date") == _scanner_et_now().strftime("%Y-%m-%d"))
                    _US["scanner_ran_today"] = _full_scan_ran

                    _label = "🟢 Scan complete" if _full_scan_ran else "🟡 Pre-market (waiting for 9:30 open)"
                    logger.info("scan_tick", extra={
                        "event": "scan_tick", "watchlist": wl,
                        "full_scan": _full_scan_ran,
                    })
                    log_event("INFO", "scanner",
                              f"{_label}. Watchlist: {', '.join(wl)}")
                except Exception as _ex:
                    logger.warning("Pre-market scan failed: %s — using anchors", _ex)
                    _US["scan_watchlist"]    = ["SPY", "QQQ"]
                    _US["scanner_ran_today"] = False
                    _US["current_ticker"]    = "SPY"

            # ── Refresh account balance + recompute session P&L ─────────────
            # Balance is fetched from Alpaca once per batch cycle (every ~60s)
            # so the dashboard always shows current equity.
            try:
                _acct_tick = alpaca.get_account()
                _bal_tick  = float(_acct_tick.get("equity", 0)) if _acct_tick else 0
                if _bal_tick > 0:
                    _US["account_balance"] = _bal_tick
                    _dsb = _US.get("day_start_balance") or _bal_tick
                    _spnl = round(_bal_tick - _dsb, 2)
                    _US["session_pnl"] = _spnl
                    # Persist so the WebSocket + bot_state.json stay in sync
                    from config import save_settings as _save_bal
                    _save_bal({"last_known_balance": round(_bal_tick, 2)})
            except Exception as _bal_err:
                logger.debug("Balance refresh failed (non-fatal): %s", _bal_err)

            # ── Batch-evaluate ALL watchlist tickers once per bar ────────────
            # Old design: one ticker per 10-second tick.  With 10 tickers the
            # cycle took ~100 s, so each ticker was only seen every 1.5 bars.
            _wl_batch = _US.get("scan_watchlist") or ["SPY", "QQQ"]
            for _bi in range(len(_wl_batch)):
                if _stop.is_set():
                    break
                _tick(alpaca, tradier)

        except DailyLossLimitReached as e:
            _US["status"] = "kill_locked"
            send_alert("DAILY LOSS LIMIT — KILL LOCK ACTIVE", str(e))
            try:
                _panic_close_all_positions(alpaca, tradier, user_id=user_id)
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
            _US["status"]      = "error"
            _US["last_update"] = _now_et().isoformat()
            try:
                json.dump({
                    "running":    True,
                    "status":     "error",
                    "last_error": str(e)[:200],
                    "last_update": _US["last_update"],
                    "account_balance": _US.get("account_balance", 0),
                    "market_open": _US.get("market_open", False),
                }, open(get_bot_state_path(user_id), "w"))
            except Exception:
                pass
            _stop.wait(timeout=30)

        # ── Sleep until the next 60-second bar boundary ───────────────────────
        # Inside the trading window: sleep to the start of the next 1-minute
        # candle so every tick sees fresh bars.  Floor at 5 s so a slow pass
        # "Trading loop stopped" log with no error message.
        try:
            _now_et_sl = _now_et()
            _hm        = _now_et_sl.hour * 60 + _now_et_sl.minute
            _balance   = _US.get("account_balance", 0)
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
            _stop.wait(timeout=poll_interval)

    # Only log "stopped" when the stop was intentional (_stop_event was set).
    # Unexpected exits (exceptions escaping the loop body) are already logged
    if _stop.is_set():
        logger.info("Trading loop stopped")
    else:
        logger.warning("Trading loop exited unexpectedly — will be restarted by auto-start")


def stop_loop(user_id: str = "admin") -> None:
    """Signal the loop for a given user to exit.

    FIX: this used to also unconditionally set the global LIVE_STATE alias
    (== admin's state) "running" = False and write the single shared root
    bot_state.json — so any user's Stop button also marked admin's dashboard
    stopped, and wrote to a file only admin's session actually read. Now
    scoped entirely to the calling user's own state and state file.
    """
    _get_stop_event(user_id).set()
    get_user_state(user_id)["running"] = False
    # Log to the database so the THINKING panel shows confirmation that the bot
    # actually received the stop signal (not just a network disconnect).
    try:
        from database import log_event
        log_event("INFO", "trading_logic", "🔴 Bot stopped.")
    except Exception:
        pass
    try:
        _state_path = get_bot_state_path(user_id)
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
