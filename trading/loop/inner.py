"""
trading/loop/inner.py — _run_trading_loop_inner(): the main trading loop's
inner body.

Split out of the old single trading/loop.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.

Kept as ONE function (irreducible, same exception class already applied
this session to trading/entry/tick.py::_tick, backtester/simulate.py::
_simulate_day, backtester/market_data.py::_load_market_data, and others):
this is a long-lived per-tick state machine built on heavy local mutable
state (_US, _prev_opt_px, _stop, day_start_balance, ...) that is read and
written across every phase of the loop (startup reconciliation, watchlist
restore, after-hours sleep, daily scan, balance refresh, batch tick,
error handling, smart sleep). Splitting it into smaller functions would
mean threading a dozen mutable locals through function-call boundaries
for no real readability gain, and would risk subtly breaking the exact
order-of-operations this loop depends on.
"""

import json
import logging
import math
import time
from datetime import timedelta

from trading.state import _now_et, _get_stop_event, get_user_state, set_user_risk
from config import get_bot_state_path, atomic_write_json
from trading.loop.audits import (
    _run_nightly_ticker_qualification_once,
    _run_weekly_strategy_review_once,
)

logger = logging.getLogger("celo_trader.trading_logic")


def _run_trading_loop_inner(user_id: str, poll_interval: int = 10) -> None:
    """Inner body of the trading loop — called exclusively from run_trading_loop()."""
    from broker import get_clients
    from config import get_api_keys, get_settings, get_trading_windows as _gtw
    from database import init_db, log_event, get_all_trades, get_open_trades
    from risk import RiskManager, DailyLossLimitReached
    from alerts import send_alert
    from scanner import get_watchlist, run_scan, is_scan_window
    from trading.entry import _tick
    from trading.diagnostics import _check_ghost_positions
    from trading.controls.panic import service_daily_loss_halt
    from risk.kill_lock import flatten_pending

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

    _settings = get_settings()
    _is_paper = bool(_settings.get("paper_trading", True))
    _broker_provider = str(_settings.get("broker_provider") or "alpaca").lower()
    credentials = get_api_keys(user_id)
    from broker import required_broker_credentials
    if not all(
        str(credentials.get(key) or "").strip()
        for key, _label in required_broker_credentials(
            credentials, provider=_broker_provider, paper=_is_paper,
        )
    ):
        _US.update({
            "running": False,
            "mode": "stopped",
            "account_balance": 0.0,
            "day_start_balance": 0.0,
            "options_buying_power": 0.0,
            "network_ok": False,
        })
        atomic_write_json(get_bot_state_path(user_id), dict(_US))
        logger.error("Bot start rejected for user %s: broker credentials are incomplete", user_id)
        return

    init_db()
    alpaca, tradier = get_clients()

    # Determine mode from settings (written by start_bot() before the loop starts).
    _trade_mode = "paper" if _is_paper else "live"
    # Accounts saved before broker-account attribution existed have no stored
    # identity yet. Resolve it once at startup so their legacy local history
    # cannot be mistaken for current-account performance. This is metadata
    # only; it neither changes the connected client nor sends an order.
    if not _settings.get("active_broker_account_id"):
        try:
            from config import get_api_keys, save_settings
            from broker.account_identity import resolve_account_identity
            account = alpaca.get_account()
            identity_key = get_api_keys().get(
                (
                    "tradier_api_key" if _is_paper else "tradier_market_api_key"
                ) if _broker_provider == "tradier" else "alpaca_api_key",
                "",
            )
            identity = resolve_account_identity(
                identity_key, _is_paper, account, provider=_broker_provider,
            )
            save_settings({"active_broker_account_id": identity})
            _settings["active_broker_account_id"] = identity
            logger.info("Initialised broker account identity for %s mode", _trade_mode)
        except Exception:
            logger.warning("Could not initialise broker account identity at startup", exc_info=True)
    _US["mode"] = _trade_mode
    _US["broker_account_id"] = _settings.get("active_broker_account_id") or None

    try:
        acct    = alpaca.get_account()
        balance = float(acct.get("equity", 0)) if acct else 0
        if not acct or "equity" not in acct or not math.isfinite(balance):
            raise RuntimeError(f"{_broker_provider.title()} returned no valid account equity")
        else:
            from config import save_settings as _save_start
            _save_start({"last_known_balance": round(balance, 2)})
    except Exception as e:
        logger.error("Cannot fetch account balance: %s", e)
        _US.update({
            "running": False,
            "mode": "stopped",
            "account_balance": 0.0,
            "day_start_balance": 0.0,
            "options_buying_power": 0.0,
            "network_ok": False,
        })
        atomic_write_json(get_bot_state_path(user_id), dict(_US))
        return

    _US["account_balance"] = balance

    # Day-start balance: prefer the broker's official prior-session close so
    # an intraday restart can never redefine today's open after trades have
    # already occurred. Tradier does not expose that field, so it retains the
    # first balance persisted for the calendar date.
    from config import save_settings as _save_dsb
    from trading.session_equity import resolve_day_start_balance
    _today_key = f"day_start_{_now_et().date().isoformat()}"
    _saved_dsb = get_settings().get(_today_key)
    day_start_balance, _day_start_source = resolve_day_start_balance(
        acct, current_equity=balance, persisted_balance=_saved_dsb,
    )
    if round(float(_saved_dsb or 0), 2) != day_start_balance:
        _save_dsb({_today_key: round(day_start_balance, 2)})
    _US["day_start_balance"] = day_start_balance
    logger.info(
        "day_open_resolved date=%s balance=%.2f source=%s",
        _now_et().date().isoformat(), day_start_balance, _day_start_source,
    )

    try:
        _US["session_pnl"] = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(
                limit=100, mode=_trade_mode,
                broker_account_id=_US.get("broker_account_id"),
            )
            if (t.get("exit_time") or "")[:10] == _now_et().date().isoformat()
        )
    except Exception as e:
        logger.error("Could not recompute session_pnl from DB at startup: %s", e)
        _US["session_pnl"] = 0.0

    # FIX: was `_em._risk = RiskManager(...)` — a module-level global on
    # trading.entry shared by every user's thread (see trading/state.py's
    # get_user_risk/set_user_risk docstring for the full explanation).
    set_user_risk(RiskManager(account_balance=balance, equity_reader=alpaca.get_account), user_id)
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
                # get_watchlist() repairs older daily files by including every
                # ticker exposed through Daily Brief scan_details as well as
                # the persisted universe. Pins stay first for UI consistency.
                _restored_wl = list(dict.fromkeys(_pins_r + get_watchlist()))
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

    # Rebuild durable position state before the first market-data tick. A
    # restart must not briefly show an empty dashboard or forget an armed
    # trailing/peak state while the broker still holds the contract.
    _prev_opt_px      = None
    _prev_opt_px_time = None
    _prev_state       = {}
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

    try:
        _restored_open = get_open_trades(
            broker_account_id=_US.get("broker_account_id"),
        )
        _US["open_trades"] = _restored_open
        _US["open_trade"] = _restored_open[0] if _restored_open else None
        _prior_positions = dict(_prev_state.get("open_positions") or {})
        _dashboard_positions = {}
        for _trade in _restored_open:
            _tid = int(_trade["id"])
            _saved = dict(_prior_positions.get(str(_tid)) or {})
            _saved.setdefault("trade_id", _tid)
            _saved.setdefault("contract_symbol", _trade.get("contract_symbol"))
            _saved.setdefault("ticker", _trade.get("ticker"))
            _saved.setdefault("option_type", _trade.get("option_type"))
            _saved.setdefault("entry_price", _trade.get("entry_price"))
            _saved.setdefault("contracts", _trade.get("contracts"))
            _saved.setdefault("entry_time", _trade.get("entry_time"))
            _US["positions"][_tid] = dict(_saved)
            _dashboard_positions[str(_tid)] = _saved
        if _restored_open:
            _US["status"] = "in_trade"
        elif _US.get("status") == "in_trade":
            _US["status"] = "scanning"
    except Exception as _restore_err:
        logger.error("Open-position restart reconstruction failed: %s", _restore_err)
        _restored_open = []
        _dashboard_positions = {}

    # Write initial bot_state.json, carrying forward last-known option price.
    _US["current_option_price"]      = _prev_opt_px
    _US["current_option_price_time"] = _prev_opt_px_time
    try:
        _state_path_start = get_bot_state_path(user_id)
        atomic_write_json(_state_path_start, {
            "running":              True,
            "auto_start_disabled":  False,   # clear explicit-stop flag on fresh start
            "mode":                 _trade_mode,   # "paper" or "live" — shown in dashboard
            "broker_account_id":    _US.get("broker_account_id"),
            "account_balance":      float(balance),
            "session_pnl":          _US.get("session_pnl", 0.0),
            "day_start_balance":    _US.get("day_start_balance", balance),
            "status":               _US.get("status", "starting"),
            "current_ticker":       _US.get("current_ticker"),
            "last_signal":          None,
            "market_open":          False,
            "last_update":          time.strftime("%H:%M:%S"),
            "current_option_price":      _prev_opt_px,
            "current_option_price_time": _prev_opt_px_time,
            "open_positions":       _dashboard_positions,
        })
    except Exception:
        pass

    while not _stop.is_set():
        try:
            # Maintenance is a global operator safety control. Checking in the
            # loop also halts accounts that were running before it was enabled.
            from config import get_maintenance_state
            _maintenance = get_maintenance_state()
            if _maintenance.get("maintenance_mode", False) and not _maintenance.get("collection_only", False):
                log_event("WARNING", "trading_logic", "🔧 Global maintenance halt received — stopping bot.")
                _stop.set()
                break
            if _maintenance.get("maintenance_mode", False):
                log_event("INFO", "trading_logic", "🔬 Maintenance collection-only mode — scanning without sending orders.")

            from broker.recovery import reconcile_orders
            _pending_execution = reconcile_orders(alpaca)
            if not _maintenance.get("maintenance_mode", False):
                service_daily_loss_halt(alpaca, tradier, user_id=user_id)

            # ── After-hours deep sleep: 5:00 PM – 8:00 AM ET ─────────────────
            # No scan, no tick, no API calls. Wakes at 8:00 AM on the next
            # weekday. Sleeps in 5-minute chunks so Stop Bot still responds.
            _now_et_ah = _now_et()
            _hm_ah     = _now_et_ah.hour * 60 + _now_et_ah.minute
            _AFTER_HOURS = _hm_ah >= 17 * 60 or _hm_ah < 8 * 60

            if _AFTER_HOURS and flatten_pending():
                # Keep recovery alive without repeatedly running overnight scans.
                _stop.wait(timeout=30)
                continue

            if _AFTER_HOURS and not flatten_pending():
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
                    # Daily evidence is now built from the account-scoped event
                    # tape and real trades.  Do not also launch the legacy
                    # eight-ticker bar replay here: after the research universe
                    # expanded, that duplicate diagnostic could monopolize a CPU
                    # core for about an hour after every service restart.  Its
                    # explicit admin/on-demand route remains available.
                    _run_nightly_ticker_qualification_once()
                    _run_weekly_strategy_review_once(alpaca)

                # Sleep up to 5 min at a time so Stop Bot stays responsive.
                # FIX: this used to wait on the module-level admin-only
                # _stop_event instead of this user's own _stop — a non-admin
                # user's Stop button wouldn't wake their thread during
                # after-hours sleep, and admin's Stop would wrongly wake
                # everyone else's.
                _stop.wait(timeout=min(10 if _pending_execution else 300, _secs_until_wake))
                continue   # skip scan + _tick entirely

            # Waking up from after-hours — log once.
            if _US.get("_after_hours_sleeping"):
                _US["_after_hours_sleeping"] = False
                log_event("INFO", "trading_logic",
                          "🌅 Good morning — resuming pre-market watch.")

            # ── Daily scan ───────────────────────────────────────────────────
            # Run if: scan hasn't run today AND we're in the scan window.
            # Outside that window, keep the safe startup seed rather than
            # launching a new universe scan from a dashboard visit or restart.
            _needs_scan = not _US.get("scanner_ran_today") and is_scan_window()
            if _needs_scan:
                try:
                    wl = run_scan(alpaca, max_tickers=30)
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
                    _morning_scan_locked = (
                        _du.get("date") == _scanner_et_now().strftime("%Y-%m-%d")
                        and bool(_du.get("universe"))
                    )
                    _US["scanner_ran_today"] = _morning_scan_locked

                    _label = "🟢 Morning scan locked" if _morning_scan_locked else "🟡 Waiting for morning scan"
                    logger.info("scan_tick", extra={
                        "event": "scan_tick", "watchlist": wl,
                        "morning_scan_locked": _morning_scan_locked,
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
            _balance_valid = False
            try:
                _acct_tick = alpaca.get_account()
                _bal_tick  = float(_acct_tick.get("equity", 0)) if _acct_tick else 0
                if _acct_tick and "equity" in _acct_tick and math.isfinite(_bal_tick):
                    _US["account_balance"] = _bal_tick
                    _today_key_tick = f"day_start_{_now_et().date().isoformat()}"
                    _saved_dsb_tick = get_settings().get(_today_key_tick)
                    _dsb, _dsb_source = resolve_day_start_balance(
                        _acct_tick,
                        current_equity=_bal_tick,
                        persisted_balance=_saved_dsb_tick,
                    )
                    _US["day_start_balance"] = _dsb
                    _spnl = round(_bal_tick - _dsb, 2)
                    _US["session_pnl"] = _spnl
                    # Persist so the WebSocket + bot_state.json stay in sync
                    from config import save_settings as _save_bal
                    _balance_update = {"last_known_balance": round(_bal_tick, 2)}
                    if round(float(_saved_dsb_tick or 0), 2) != _dsb:
                        _balance_update[_today_key_tick] = round(_dsb, 2)
                        logger.info(
                            "day_open_resolved date=%s balance=%.2f source=%s",
                            _now_et().date().isoformat(), _dsb, _dsb_source,
                        )
                    _save_bal(_balance_update)
                    _balance_valid = True
            except Exception as _bal_err:
                logger.debug("Balance refresh failed (non-fatal): %s", _bal_err)

            # Trading stays single-writer. Research has separate readers/state
            # and no order capabilities; its duration never sets our cadence.
            from trading.loop.scan_schedule import scan_universe, run_execution_batch
            from trading.loop.research_worker import submit_research
            from trading.state import get_user_risk
            _scan_settings = get_settings()
            _wl_batch = scan_universe(_US.get("scan_watchlist") or ["SPY", "QQQ"], _scan_settings)
            _US["scan_watchlist"] = _wl_batch
            _research_minute = _now_et().strftime("%Y-%m-%dT%H:%M")
            if _US.get("research_submitted_minute") != _research_minute:
                _submitted = submit_research(user_id, _stop, {
                    "tickers": _wl_batch, "settings": _scan_settings,
                    "balance": _US.get("account_balance", 0), "risk": get_user_risk(),
                })
                if _submitted:
                    _US["research_submitted_minute"] = _research_minute
            from trading.loop.daily_loss import run_guarded_execution
            run_guarded_execution(
                risk=get_user_risk(), balance=_US.get("account_balance", 0),
                balance_valid=_balance_valid,
                collection_only=bool(_maintenance.get("maintenance_mode", False)),
                broker=alpaca, market=tradier, user_id=user_id,
                execute=lambda: run_execution_batch(_wl_batch, _scan_settings, _stop, _tick, alpaca, tradier),
            )

        except DailyLossLimitReached as e:
            _US["status"] = "kill_locked"
            try:
                service_daily_loss_halt(alpaca, tradier, user_id=user_id)
            except Exception as _ce:
                logger.error("Panic close on kill lock failed: %s", _ce)
            logger.warning("Daily-loss entries halted; close confirmations retry on subsequent cycles")
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
                atomic_write_json(get_bot_state_path(user_id), {
                    "running":    True,
                    "status":     "error",
                    "last_error": str(e)[:200],
                    "last_update": _US["last_update"],
                    "account_balance": _US.get("account_balance", 0),
                    "market_open": _US.get("market_open", False),
                })
            except Exception:
                pass
            _stop.wait(timeout=30)

        # Short boundary-aligned retries handle a forming/late minute without
        # depending on the length of the independent research pass.
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
            if _US.get("daily_loss_close_pending"):
                _stop.wait(timeout=10)
            elif _in_window:
                from trading.loop.scan_schedule import seconds_until_scan
                _stop.wait(timeout=seconds_until_scan(_now_et_sl))
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
