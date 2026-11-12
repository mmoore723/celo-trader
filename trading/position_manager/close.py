"""
trading/position_manager/close.py — Exit order execution + trade closeout.

Split out of trading/position_manager.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. _close_position() is left as one function
for the same reason manage.py's main function is: a single sequential
routine (place exit order -> handle partial fill -> record P&L -> reset
per-user state -> arm flip-trade) built on local state threaded through to
the end — splitting it across files would risk the exact kind of subtle
behavior change this cleanup is supposed to avoid on live order-execution
code (rule 6).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from trading.state import get_user_state, get_user_risk, get_user_trade_log, set_user_trade_log, _now_et
from config import get_bot_state_path
from trading.position_manager.helpers import _snapshot_exit_annotations, _reconcile_if_phantom
from trading.decision_trace import exit_order

logger = logging.getLogger("celo_trader.trading_logic")


def _close_position(
    alpaca: "AlpacaClient",
    trade: dict,
    exit_price: Optional[float],
    reason: str,
    bid_price: Optional[float] = None,
    mtf_notes: Optional[list] = None,
    reference_quote: Optional[dict] = None,
    pricing_unavailable: bool = False,
) -> None:
    from config.research_order_specs import SPECS
    from trading.research_session_clock import uses_broker_session
    if uses_broker_session(trade):
        from trading.research_session_clock import session_close_if_open
        if session_close_if_open(alpaca, _now_et()) is None:
            return
    _US        = get_user_state()
    _risk      = get_user_risk()
    _trade_log = get_user_trade_log()

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

    _balance_close  = _US.get("account_balance", STARTING_CAPITAL)
    _rpct_close     = get_risk_tier(_balance_close)
    _tier_label = (
        "Tier4_5pct" if _rpct_close >= BOOTSTRAP_RISK_PCT else
        "Tier3_3pct" if _rpct_close >= _GMT_TL else
        "Tier2_2pct" if _rpct_close >= _MTT_TL else
        "Tier1_1pct"
    )

    if pricing_unavailable and (not reason or reason.startswith('stage1')):
        raise ValueError('Unpriced full exit requires a full liquidation reason')
    if paper:
        logger.info("[PAPER] SELL %s reference=%s (%s)", trade["contract_symbol"], exit_price, reason)
    _urgent_exit = any(token in (reason or "").lower() for token in (
        "hard_stop", "initial_atr_stop", "structural_stop", "panic",
        "kill_lock", "daily_loss", "session_hard_cutoff", "research_session_close",
    ))
    from trading.tsla_giveback_exit import use_giveback_market_order
    _giveback_market = use_giveback_market_order(trade, reason, paper)
    _session_market = uses_broker_session(trade) and reason in {'research_session_close', 'session_hard_cutoff_355pm'}
    _failed_range_deadline = trade.get('strategy_id') == 'RESEARCH_FAILED_RANGE_V2' and reason == 'research_failed_range_30m'
    _tsla_pending_exit = trade.get('strategy_id') == 'V2_TSLA_TWO_LEG_TREND_PULLBACK' and bool(
        _US.get('positions', {}).get(trade['id'], {}).get('exit_pending_reason')
    )
    _market_exit = pricing_unavailable or _giveback_market or _session_market or _failed_range_deadline or _tsla_pending_exit
    if reason == 'giveback_25pct':
        # This new optional policy is paper-only. A retained signal must never
        # turn into an unbounded market sell when the next quote gaps down.
        if not paper or trade.get('paper') not in (True, 1):
            raise ValueError('Premium giveback is not authorized for live execution')
        from decimal import Decimal, ROUND_CEILING
        from strategy_health.premium_rules import giveback_bid_floor
        floor=float(giveback_bid_floor(trade['entry_price']).quantize(Decimal('.01'),rounding=ROUND_CEILING))
        exit_price=max(float(exit_price or 0),floor)
        bid_price=max(float(bid_price or 0),floor)
        _market_exit=False
        _urgent_exit=False
    fill = exit_order(alpaca.place_option_order, trade,
        symbol          = trade["contract_symbol"],
        qty             = trade["contracts"],
        side            = "sell",
        order_type      = "market" if _market_exit else "limit",
        limit_price     = None if _market_exit else exit_price,
        step_to_price   = None if _market_exit else bid_price,
        allow_market_fallback = _urgent_exit,
        position_intent = "sell_to_close",
        # The strategy has already selected bid or midpoint-then-bid from
        # this exact Tradier contract. Do not overwrite it with another feed.
        price_authority = "tradier" if reference_quote or reason == 'giveback_25pct' else "alpaca",
        order_context   = {
            "ticker": trade.get("ticker"),
            "strategy_id": trade.get("strategy_id"),
            "trade_id": trade.get("id"),
            "expected_contracts": trade["contracts"],
            "exit_reason": reason,
            "exit_annotations": _snapshot_exit_annotations(trade.get("ticker", "")),
            "peak_price": _US["positions"].get(trade["id"], {}).get("peak_price"),
            "mae_price": _US["positions"].get(trade["id"], {}).get("min_price"),
            # Price source and execution broker are separate. The real fill
            # still comes only from Alpaca's confirmed order response.
            "quote_source": (reference_quote or {}).get("quote_source") or "tradier_exit_quote",
            "quote_bid": (reference_quote or {}).get("bid"),
            "quote_ask": (reference_quote or {}).get("ask"),
            "quote_mid": (reference_quote or {}).get("mid"),
            "quote_received_at": (reference_quote or {}).get("quote_received_at"),
            "quote_bid_time_ms": (reference_quote or {}).get("bid_date"),
            "quote_ask_time_ms": (reference_quote or {}).get("ask_date"),
        },
    )

    if fill is None:
        if _reconcile_if_phantom(alpaca, trade):
            return
        log_event("WARNING", "trading_logic",
                  f"⚠️ [{trade['contract_symbol']}] Exit not fully confirmed — "
                  f"checking the original order and actual remaining quantity next tick.")
        return

    if (_market_exit or pricing_unavailable) and not (fill.get('confirmed_fill_price') or fill.get('filled_avg_price')):
        return
    fill_price = float(fill.get("confirmed_fill_price") or
                       fill.get("filled_avg_price") or exit_price)

    # Exit quote/fill evidence for PAPER trades.  This is recorded only after
    # the broker confirmed a fill, so rejected exit attempts cannot masquerade
    # as completed research observations.
    if paper:
        try:
            from database import record_paper_option_quote
            record_paper_option_quote(
                trade_id=trade["id"],
                contract_symbol=trade["contract_symbol"],
                observation_kind="exit",
                observed_at=_now_et(),
                quote=reference_quote or ({} if _market_exit else {"bid": bid_price, "mid": exit_price}),
                source=(
                    "tradier_pre_submit_exit_quote"
                    if reference_quote else "exit_order"
                ),
                fill_price=fill_price,
            )
        except Exception:
            logger.warning("paper exit quote capture failed for trade %s", trade.get("id"), exc_info=True)

    # FIX 2026-07-20 (Alpaca fills audit): broker.py may return a PARTIAL
    # fill for an exit order. Mirror the stage-1 partial-exit pattern: record
    # only what actually closed, shrink the parent row, leave it OPEN so the
    # next tick re-evaluates the true remainder.
    _closed_qty = int(fill.get("filled_qty", trade["contracts"]))
    if _closed_qty < 1:
        log_event(
            "WARNING", "trading_logic",
            f"🟡 [{trade['contract_symbol']}] Exit order reported filled but 0 "
            f"contracts actually closed — trade stays open, will retry next tick.",
        )
        return
    if _closed_qty < trade["contracts"]:
        _remaining_qty = trade["contracts"] - _closed_qty
        log_event(
            "WARNING", "trading_logic",
            f"🟡 [{trade['contract_symbol']}] Exit only filled {_closed_qty} of "
            f"{trade['contracts']} contract(s) — closing the filled portion and "
            f"leaving {_remaining_qty} contract(s) open, will retry the "
            f"remainder next tick.",
        )
        logger.warning(
            "partial_fill_exit: trade_id=%s requested=%d filled=%d",
            trade["id"], trade["contracts"], _closed_qty,
        )
        from database import insert_trade, get_conn
        _trade_ps_partial = _US["positions"].get(trade["id"], {})
        partial_id = fill.get("accounted_trade_id") or insert_trade(
            ticker          = trade["ticker"],
            contract_symbol = trade["contract_symbol"],
            option_type     = trade["option_type"],
            strike          = trade["strike"],
            expiry          = trade["expiry"],
            contracts       = _closed_qty,
            entry_price     = trade.get("entry_price", 0),
            entry_time      = trade["entry_time"] if isinstance(trade["entry_time"], datetime) else datetime.fromisoformat(trade["entry_time"]),
            entry_reason    = trade.get("entry_reason", ""),
            paper           = paper,
            strategy_id     = trade.get("strategy_id", "UNKNOWN"),
            annotations_json= trade.get("annotations_json"),
            strategy_context_json=trade.get("strategy_context_json"),
            broker_account_id= trade.get("broker_account_id"),
            candidate_id     = trade.get("candidate_id"),
            parent_trade_id  = trade.get("parent_trade_id") or trade.get("id"),
            entry_order_id   = trade.get("entry_order_id"),
            entry_fill_time  = trade.get("entry_fill_time"),
        )
        if not fill.get("accounted_trade_id"):
            close_trade(
                trade_id             = partial_id,
                exit_price           = exit_price,
                exit_time            = _now_et(),
                exit_reason          = reason,
                confirmed_fill_price = fill_price,
                peak_price           = _trade_ps_partial.get("peak_price"),
                mae_price            = _trade_ps_partial.get("min_price"),
                paper                = paper,
                annotations_json     = _snapshot_exit_annotations(trade.get("ticker", "")),
                exit_order_id        = str(fill.get("id") or "") or None,
                exit_fill_time       = fill.get("filled_at") or _now_et(),
            )
        try:
            from database import link_broker_order_to_trade
            link_broker_order_to_trade(
                str(fill.get("id") or ""), partial_id, link_kind="partial exit",
            )
        except Exception:
            logger.warning("partial exit order-flow link failed for trade %s", partial_id, exc_info=True)

        try:
            from ai_reasoning.narrator import narrate_exit
            _pf_direction = "bullish" if (trade.get("option_type") or "call").lower() == "call" else "bearish"
            _pf_elapsed_min = 0.0
            try:
                from database.helpers import _to_et_datetime
                _pf_entry_dt = _to_et_datetime(trade["entry_time"])
                _pf_elapsed_min = (_now_et() - _pf_entry_dt).total_seconds() / 60
            except Exception:
                pass
            narrate_exit(
                ticker           = trade.get("ticker", "?"),
                trade_id         = partial_id,
                contract_symbol  = trade["contract_symbol"],
                strategy_id      = trade.get("strategy_id"),
                direction        = _pf_direction,
                reason           = reason,
                entry_price      = trade.get("entry_price", 0),
                current_price    = fill_price,
                elapsed_minutes  = _pf_elapsed_min,
                mtf_notes        = mtf_notes,
                peak_price       = _trade_ps_partial.get("peak_price"),
                min_price        = _trade_ps_partial.get("min_price"),
            )
        except Exception as _ai_ex:
            logger.debug("ai_reasoning narrate_exit dispatch failed (non-fatal): %s", _ai_ex)

        if not fill.get("accounted_trade_id"):
            with get_conn() as _conn:
                _conn.execute(
                    "UPDATE trades SET contracts = ? WHERE id = ?",
                    (_remaining_qty, trade["id"]),
                )
        return

    _trade_ps = _US["positions"].get(trade["id"], {})
    _peak_px  = _trade_ps.get("peak_price")
    _min_px   = _trade_ps.get("min_price")

    _entry_px   = float(trade.get("entry_price", 0) or 0)
    _contracts  = int(trade.get("contracts", 1) or 1)
    _ticker_r   = trade.get("ticker", "?")
    _strat_r    = trade.get("strategy_id", "?")
    _opt_r      = (trade.get("option_type") or "option").upper()
    _REASON_MAP = {
        "stage1":                   "Stage 1 profit-lock hit (dynamic trigger) — bot locked in half the position and moved the stop to breakeven",
        "stage2_break_even":        "Stop-to-breakeven triggered — the remainder exited at no loss after Stage 1 ran",
        "stage2_trail_stop":        "Trailing stop activated after locking in profit — price pulled back and the floor was hit",
        "atr_trail_stop":           "ATR/swing trailing stop tightened and triggered as price pulled back from the high",
        "initial_atr_stop":         "Initial ATR-based stop hit early — the trade moved against us before the trailing stop could arm",
        "vwap_trend_dead":          "VWAP breach plus trend breakdown confirmed — bot exited to avoid a larger loss",
        "structural_stop_bar_high": "Structural stop hit at the rejection level — the setup invalidated",
        "time_cap_loser":           "20-minute time cap hit without a confirming move — flat/losing trade closed to free capital",
        "time_cap_winner":          "90-minute maximum hold cap reached — winner closed to avoid late-day decay",
        "manual":                   "manually closed by the user",
        "panic":                    "emergency close triggered (kill-switch or account risk limit)",
        "kill_lock_force_close":    "daily loss limit reached — all positions force-closed to protect the account",
        "simplified_hard_stop":       "hard stop hit — structural or ATR-based catastrophe stop",
        "simplified_chandelier_3atr": "chandelier exit (3.0x ATR trailing stop) triggered as price pulled back from the high",
        "simplified_time_cap":        "time cap hit — trade closed to stop theta bleed on a stalled position",
    }
    _reason_txt = next((v for k, v in _REASON_MAP.items() if reason and k in reason), reason or "exit signal")
    _dur_secs   = 0
    try:
        from database.helpers import _to_et_datetime
        _et_str = trade.get("entry_time", "")
        if _et_str:
            _entry_dt = _to_et_datetime(_et_str)
            _dur_secs = int((_now_et() - _entry_dt).total_seconds())
    except Exception:
        _dur_secs = 0
    _dur_txt = (
        f"{_dur_secs // 60}m {_dur_secs % 60}s" if _dur_secs < 3600
        else f"{_dur_secs // 3600}h {(_dur_secs % 3600) // 60}m"
    ) if _dur_secs > 0 else "unknown duration"
    _mfe_txt  = f" — the option peaked at ${_peak_px:.2f} ({round((_peak_px - _entry_px) / _entry_px * 100, 1):+.1f}% from entry)" if _peak_px and _entry_px > 0 else ""
    _mae_txt  = f", dipped as low as ${_min_px:.2f} ({round((_min_px - _entry_px) / _entry_px * 100, 1):+.1f}%)" if _min_px and _entry_px > 0 else ""
    _recap = (
        f"Strategy: {_strat_r} | {_ticker_r} {_opt_r} | "
        f"Entry ${_entry_px:.2f} → Exit ${fill_price:.2f} | "
        f"{_contracts} contract{'s' if _contracts != 1 else ''} | Hold: {_dur_txt}. "
        f"Exit: {_reason_txt}{_mfe_txt}{_mae_txt}."
    )

    pnl = fill["accounted_pnl"] if fill.get("accounted_trade_id") else close_trade(
        trade_id             = trade["id"],
        exit_price           = exit_price,
        exit_time            = _now_et(),
        exit_reason          = reason,
        confirmed_fill_price = fill_price,
        peak_price           = _peak_px,
        mae_price            = _min_px,
        paper                = paper,
        recap                = _recap,
        annotations_json     = _snapshot_exit_annotations(trade.get("ticker", "")),
        exit_order_id        = str(fill.get("id") or "") or None,
        exit_fill_time       = fill.get("filled_at") or _now_et(),
    )
    try:
        from database import link_broker_order_to_trade
        link_broker_order_to_trade(
            str(fill.get("id") or ""), trade["id"], link_kind="exit",
        )
    except Exception:
        logger.warning("exit order-flow link failed for trade %s", trade.get("id"), exc_info=True)

    try:
        _ticker_close = trade.get("ticker", "?")
        _opt_close    = trade.get("option_type", "option").upper()
        _entry_px     = trade.get("entry_price", 0)
        _pnl_sign     = "+" if pnl >= 0 else ""
        _reason_map   = {
            "stage1":                    "first profit target hit (dynamic trigger)",
            "stage2_break_even":         "remainder hit break-even stop",
            "stage2_trail_stop":         "trail stop triggered (locked profit floor)",
            "atr_trail_stop":            "ATR/swing trailing stop hit",
            "initial_atr_stop":          "initial ATR stop hit early (before trail could arm)",
            "vwap_trend_dead":           "VWAP breach + trend breakdown confirmed",
            "structural_stop_bar_high":  "structural stop (rejection level) hit",
            "time_cap_loser":            "20-min cap (flat/losing — no setup confirmation)",
            "time_cap_winner":           "90-min cap (maximum hold for winners)",
            "manual":                    "manually closed by user",
            "panic":                     "emergency close triggered",
            "kill_lock_force_close":     "daily loss limit — force closed",
            "simplified_hard_stop":       "hard stop (structural/ATR)",
            "simplified_chandelier_3atr": "chandelier exit (3.0x ATR trail)",
            "simplified_time_cap":        "time cap (theta stall)",
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

    try:
        from ai_reasoning.narrator import narrate_exit
        _close_direction = "bullish" if (trade.get("option_type") or "call").lower() == "call" else "bearish"
        narrate_exit(
            ticker           = trade.get("ticker", "?"),
            trade_id         = trade["id"],
            contract_symbol  = trade["contract_symbol"],
            strategy_id      = trade.get("strategy_id"),
            direction        = _close_direction,
            reason           = reason,
            entry_price      = _entry_px,
            current_price    = fill_price,
            elapsed_minutes  = _dur_secs / 60.0,
            mtf_notes        = mtf_notes,
            peak_price       = _peak_px,
            min_price        = _min_px,
        )
    except Exception as _ai_ex:
        logger.debug("ai_reasoning narrate_exit dispatch failed (non-fatal): %s", _ai_ex)

    if pnl > 0:
        try:
            reserved = record_sweep(pnl, trade["id"])
            _US["last_tax_sweep"] = reserved
        except Exception as e:
            logger.error("Tax sweep failed: %s", e)

    # The fill is already booked. Preserve the halt, but finish removing the
    # closed position before propagating it to the caller.
    _daily_loss_error = None
    try:
        _risk.record_pnl(pnl, account_balance=_US["account_balance"])
    except DailyLossLimitReached as exc:
        _daily_loss_error = exc

    try:
        _US["session_pnl"] = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(limit=100)
            if (t.get("exit_time") or "")[:10] == _now_et().date().isoformat()
        )
    except Exception:
        pass

    closed_utc = _now_et()
    _closed_opt_type  = trade.get("option_type", "")
    _closed_direction = "bullish" if _closed_opt_type == "call" else "bearish"

    _US["positions"].pop(trade["id"], None)

    _remaining_open               = get_open_trades()
    _US["open_trades"]     = _remaining_open
    _US["open_trade"]      = _remaining_open[0] if _remaining_open else None
    _US["status"]          = "in_trade" if _remaining_open else "scanning"
    _US["last_direction"]        = _closed_direction
    _US["last_trade_closed_time"]= closed_utc.isoformat()

    _closed_ticker = trade.get("ticker", "")
    if pnl > 0 and _closed_ticker:
        _WIN_COOLDOWN_MIN = 10
        _win_expires = _now_et() + timedelta(minutes=_WIN_COOLDOWN_MIN)
        _US.setdefault("ticker_win_cooldown", {})[_closed_ticker] = _win_expires
        log_event("INFO", "trading_logic",
                  f"⏱ [{_closed_ticker}] Post-win cooldown {_WIN_COOLDOWN_MIN} min "
                  f"(pnl=${pnl:+.2f}). No re-entry until {_win_expires.strftime('%H:%M')} ET.")

    # ── Per-ticker post-loss quality gate ────────────────────────────────
    # After a loss, record exit price/direction for the 0.3% displacement
    # check in entry.py. Also set a STRUCTURAL cooldown keyed by
    # ticker:strategy_id.
    _strat_id = trade.get("strategy_id", "")
    if pnl < 0 and _closed_ticker:
        _US.setdefault("ticker_loss_context", {})[_closed_ticker] = {
            "exit_price":   exit_price,
            "direction":    _closed_direction,
            "strategy_id":  _strat_id,
            "loss_count":   _US.get("ticker_loss_context", {}).get(
                                _closed_ticker, {}).get("loss_count", 0) + 1,
        }

    try:
        from config import atomic_update_json
        _state_path_cl = get_bot_state_path()
        def _remove_closed_position(state: dict) -> dict:
            positions = dict(state.get("open_positions") or {})
            positions.pop(str(trade["id"]), None)
            return {**state, "open_positions": positions}
        atomic_update_json(_state_path_cl, _remove_closed_position)
    except Exception:
        pass

    if _daily_loss_error is not None:
        _US["flip_eligible"] = False
        _US["flip_direction"] = None
        _US["flip_ticker"] = None
        if hasattr(_trade_log, "clear_context"):
            _trade_log.clear_context()
        set_user_trade_log(logger)
        raise _daily_loss_error

    from config import get_settings as _gs
    _is_hard_stop         = "stop" in (reason or "")
    _flip_setting_enabled = bool(_gs().get("flip_trading_enabled", True))
    if _is_hard_stop and _flip_setting_enabled:
        _flip_dir = "bearish" if _closed_direction == "bullish" else "bullish"
        _US["flip_eligible"]  = True
        _US["flip_direction"] = _flip_dir
        _US["flip_ticker"]    = _closed_ticker
        log_event("INFO", "trading_logic",
                  f"🟡 Flip armed — stopped out {_closed_direction}. "
                  f"Watching for {_flip_dir} retest entry.")
    else:
        _US["flip_eligible"]  = False
        _US["flip_direction"] = None
        _US["flip_ticker"]    = None

    _trade_log.info(
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
    if hasattr(_trade_log, "clear_context"):
        _trade_log.clear_context()
    set_user_trade_log(logger)
