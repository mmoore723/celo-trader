"""
trading/position_manager.py — Open-position management and close logic.

Functions:
  _manage_open_position — ORB two-stage exit manager (called every tick)
  _close_position       — full-close helper (stop-loss, time-box, manual, etc.)

NOTE on _risk and _trade_log:
  Both live as module-level variables in trading/entry.py because _tick()
  declares them with `global` there.  We access them through the entry module
  object at runtime (deferred import inside each function) to avoid the circular
  import that would result from a top-level cross-import.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from trading.state import LIVE_STATE, _now_et, _ET_TZ, _BOT_ROOT

logger = logging.getLogger("celo_trader.trading_logic")


def _manage_open_position(
    alpaca: "AlpacaClient",
    tradier: "TradierClient",
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
    """
    # Deferred import to access _risk and _trade_log from entry without circular dep
    from trading import entry as _em

    try:
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote is None:
            logger.warning("Cannot price %s — holding", trade["contract_symbol"])
            return

        current_price = quote["mid"]
        entry_price   = trade["entry_price"]
        trade_id      = trade["id"]

        # ── Per-position state (MAX_CONCURRENT_POSITIONS) ─────────────────────
        ps = LIVE_STATE["positions"].setdefault(trade_id, {
            "peak_price":                None,
            "entry_time":                trade.get("entry_time"),
            "stage1_done":               False,
            "stage1_be_price":           None,
            "current_stop_pct":          _em._risk.ORB_STOP_PCT if _em._risk else 0.30,
            "struct_stop_price":         None,
            "current_option_price":      None,
            "current_option_price_time": None,
            "last_position_narration_minute": None,
        })

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

        # Recover peak for DB compatibility
        from risk import persist_peak_price, recover_peak_price
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

        # ── Recompute dynamic stop each tick ──────────────────────────────────
        current_stop_pct = _em._risk.dynamic_stop_pct(entry_time, now_utc)
        ps["current_stop_pct"] = current_stop_pct

        # Persist to bot_state.json so the dashboard can see it.
        import json as _json_m
        _state_path_m = _BOT_ROOT / "bot_state.json"
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
            _existing["current_stop_pct"]          = current_stop_pct
            _existing["current_option_price"]      = current_price
            _existing["current_option_price_time"] = ps["current_option_price_time"]
            with open(_state_path_m, "w") as _f:
                _json_m.dump(_existing, _f)
        except Exception:
            pass

        _struct_stop = ps.get("struct_stop_price")

        # ── Per-minute "still in trade" narration ─────────────────────────────
        _minute_key = now_utc.strftime("%Y-%m-%d %H:%M")
        if ps.get("last_position_narration_minute") != _minute_key:
            from database import log_event
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

        should_exit, reason = _em._risk.should_exit(
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

            # Single-contract guard: can't sell half of 1 → full exit
            from database import log_event
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

            from config import get_settings
            settings = get_settings()
            paper    = settings.get("paper_trading", True)

            if paper:
                _em._trade_log.info(
                    "stage1_partial_exit",
                    extra={
                        "event":        "stage1_partial_exit",
                        "contracts_sold": half_contracts,
                        "exit_price":   round(current_price, 4),
                        "entry_price":  round(entry_price, 4),
                    },
                )
            fill = alpaca.place_option_order(
                symbol      = trade["contract_symbol"],
                qty         = half_contracts,
                side        = "sell",
                order_type  = "market",
            )

            # FIX 2026-06-15: if the order didn't fill, leave stage1_done False
            # and retry next tick — exactly like a normal failed entry order.
            if fill is None:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take order "
                    f"did not fill — position left at full size, will retry "
                    f"next tick.",
                )
                return

            fill_price = float(fill.get("filled_avg_price") or current_price)

            from database import insert_trade, close_trade, get_conn
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

            from config import STAGE2_TRAIL_PCT
            ps["stage1_done"]     = True
            ps["stage1_be_price"] = round(entry_price * (1.0 + STAGE2_TRAIL_PCT), 4)

        else:
            # ── Full exit (stop_loss, time_box, stage2 BE, or stage2 stop) ────
            _close_position(alpaca, trade, current_price, reason)

    except Exception as e:
        from database import log_event
        logger.error("Error managing ORB position: %s", e)
        log_event("ERROR", "trading_logic",
                  f"🔴 Error while monitoring open position: {type(e).__name__}. "
                  f"Will retry next tick. ({e})")


def _close_position(
    alpaca: "AlpacaClient",
    trade: dict,
    exit_price: float,
    reason: str,
) -> None:
    # Deferred import to access _trade_log and set it back to logger after close
    from trading import entry as _em

    from config import (
        get_settings, get_risk_tier,
        STARTING_CAPITAL,
        BOOTSTRAP_RISK_PCT,
        GROWTH_MODE_RISK_PCT as _GMT_TL,
        MID_TIER_RISK_PCT as _MTT_TL,
    )
    from database import log_event, close_trade, get_open_trades, get_all_trades
    from risk import DailyLossLimitReached
    from tax_engine import record_sweep

    settings = get_settings()
    paper    = settings.get("paper_trading", True)

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
    fill = alpaca.place_option_order(
        symbol      = trade["contract_symbol"],
        qty         = trade["contracts"],
        side        = "sell",
        order_type  = "market",
    )

    fill_price = exit_price
    if fill and fill.get("filled_avg_price"):
        fill_price = float(fill["filled_avg_price"])

    pnl = close_trade(
        trade_id             = trade["id"],
        exit_price           = exit_price,
        exit_time            = _now_et(),
        exit_reason          = reason,
        confirmed_fill_price = fill_price,
    )

    # ── Human-readable close narrative ────────────────────────────────────────
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
        _em._risk.record_pnl(pnl, account_balance=LIVE_STATE["account_balance"])
    except DailyLossLimitReached:
        raise

    LIVE_STATE["session_pnl"] = sum(
        t.get("realized_pnl", 0) for t in
        __import__("database").get_all_trades(limit=100)
        if t.get("exit_time", "")[:10] == date.today().isoformat()
    )
    closed_utc = _now_et()
    _closed_opt_type  = trade.get("option_type", "")
    _closed_direction = "bullish" if _closed_opt_type == "call" else "bearish"

    # Clear this position's per-trade state
    LIVE_STATE["positions"].pop(trade["id"], None)

    _remaining_open               = get_open_trades()
    LIVE_STATE["open_trades"]     = _remaining_open
    LIVE_STATE["open_trade"]      = _remaining_open[0] if _remaining_open else None
    LIVE_STATE["status"]          = "in_trade" if _remaining_open else "scanning"
    LIVE_STATE["last_direction"]        = _closed_direction
    LIVE_STATE["last_trade_closed_time"]= closed_utc.isoformat()

    _closed_ticker = trade.get("ticker", "")
    if pnl > 0:
        if _closed_ticker:
            _WIN_COOLDOWN_MIN = 10
            _win_expires = _now_et() + timedelta(minutes=_WIN_COOLDOWN_MIN)
            LIVE_STATE.setdefault("ticker_win_cooldown", {})[_closed_ticker] = _win_expires
            log_event("INFO", "trading_logic",
                      f"⏱ [{_closed_ticker}] Post-win cooldown set for {_WIN_COOLDOWN_MIN} min "
                      f"(pnl=${pnl:+.2f}). No re-entry until "
                      f"{_win_expires.strftime('%H:%M')} ET.")

    # Remove from bot_state.json open_positions
    try:
        import json as _json_cl
        _state_path_cl = _BOT_ROOT / "bot_state.json"
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

    # ── Flip-trade arming ─────────────────────────────────────────────────────
    from config import get_settings as _gs
    _is_hard_stop         = reason == "dynamic_stop_30pct"
    _flip_setting_enabled = bool(_gs().get("flip_trading_enabled", True))
    if _is_hard_stop and _flip_setting_enabled:
        _flip_dir = "bearish" if _closed_direction == "bullish" else "bullish"
        _closed_ticker = trade.get("ticker", "")
        LIVE_STATE["flip_eligible"]  = True
        LIVE_STATE["flip_direction"] = _flip_dir
        LIVE_STATE["flip_ticker"]    = _closed_ticker
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
        LIVE_STATE["flip_eligible"]  = False
        LIVE_STATE["flip_direction"] = None
        LIVE_STATE["flip_ticker"]    = None

    _em._trade_log.info(
        "trade_closed",
        extra={
            "event":                   "trade_closed",
            "Trade_ID":                trade["id"],
            "Risk_Tier_Used":          _tier_label,
            "R_R_Ratio":               "n/a",
            "Entry_Volume_Multiplier": "n/a",
            "exit_price":   round(exit_price, 4),
            "realized_pnl": round(pnl, 2),
            "exit_reason":  reason,
            "flip_armed":   _is_hard_stop and _flip_setting_enabled,
        },
    )
    if hasattr(_em._trade_log, "clear_context"):
        _em._trade_log.clear_context()
    _em._trade_log = logger
