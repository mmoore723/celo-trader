"""
trading/position_manager/manage.py — Per-tick adaptive position management.

Split out of trading/position_manager.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. _manage_open_position() is left as one
function rather than split further: it's a single sequential per-tick
routine (fetch quote -> fetch bars -> compute trail/target -> check exit ->
act) built on a large block of local state that many later steps read —
breaking it into cross-file pieces would mean threading a dozen local
variables through explicit parameters, which is exactly the kind of
mechanical-refactor-that-quietly-changes-behavior this cleanup is supposed
to avoid on live order-execution code (rule 6).

Exit hierarchy (checked in order each tick) — see risk/exits.py for the
authoritative version; documented again here since this file drives it:
  1. Hard structural stop  — entry_bar_high/low-derived option stop (always on)
  2. ATR / swing trailing stop — tighter of (peak - 1.5xATR) or last swing low/high
  3. VWAP breach + trend breakdown — only exits when ADX<20 OR EMA stack is misaligned
  4. Stage-1 profit target — dynamic gain trigger -> sell 50%, arm trailing stop
  5. Stage-2 trail floor  — remainder stops at entry x1.15 (locked-profit floor)
  6. Hard stop safety net — 20% below entry
  7. Time cap of last resort — safety net only, structure-based exits fire first

Per-position state machine keys (stored in this user's
state["positions"][trade_id], see trading/state.py::get_user_state):
  stage, phase, peak_price_opt, peak_price_under, atr_trail_stop,
  vwap_breached_at, struct_stop_price, stage1_done, stage1_be_price
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from trading.decision_trace import decision, position_cycle, traced_call, note, exit_order

from trading.state import get_user_state, get_user_risk, get_user_trade_log, _now_et, _ET_TZ
from config import get_bot_state_path
from trading.mtf_features import (
    compute_adx, ema_stack_aligned, compute_rsi, compute_macd_hist, trend_bias_1h,
)
from trading.position_manager.constants import (
    _DELTA_APPROX, _ADX_WEAK_THRESHOLD, _VWAP_BREACH_BARS, _VWAP_5M_BREACH_BARS,
    _MIN_TRAIL_WARMUP_MIN, _TRAIL_MULT_1H_WITH, _TRAIL_MULT_BASE,
    _TRAIL_MULT_1H_AGAINST, _TRAIL_MULT_TIGHT, _RSI_EXHAUST_CALL, _RSI_EXHAUST_PUT,
    _MACD_FADE_BARS, _15M_SWING_PROX_PCT, _SWING_LOOKBACK,
)
from trading.position_manager.indicators import (
    _compute_atr, _compute_vwap, _structural_swing_stop, _underlying_stop_to_option,
)
from trading.position_manager.helpers import _reconcile_if_phantom

logger = logging.getLogger("celo_trader.trading_logic")


@decision
def _resolve_latched_exit(
    position_state: dict,
    should_exit: bool,
    reason: str,
    now: datetime,
) -> tuple[bool, str]:
    """Make an exit decision sticky until the broker confirms the close.

    A structure-based condition can disappear on the next candle.  If its
    first limit order did not fill, recomputing from scratch previously let a
    real exit decision turn back into ``hold``.  The position then leaked past
    its intended exit.  Once an exit fires, keep closing for that same reason;
    `_close_position` removes the position state only after a confirmed fill.
    """
    pending_reason = str(position_state.get("exit_pending_reason") or "").strip()
    if pending_reason in ('premium_2pct','premium_25pct','giveback_25pct') and should_exit and reason not in ('premium_2pct','premium_25pct','giveback_25pct'):
        position_state['exit_pending_reason'] = reason
        return True, reason
    if pending_reason and should_exit and reason == 'research_session_close':
        position_state['exit_pending_reason'] = reason
        return True, reason
    if pending_reason == 'stage1_research_atr10' and should_exit and reason.startswith('research_'):
        position_state['exit_pending_reason'] = reason
        return True, reason
    if pending_reason:
        return True, pending_reason
    if should_exit:
        position_state["exit_pending_reason"] = str(reason or "exit_signal")
        position_state["exit_pending_since"] = now.isoformat()
        position_state["exit_attempts"] = 0
    return should_exit, reason


def _persist_exit_latch(trade_id: object, position_state: dict) -> None:
    """Persist the sticky exit across process restarts without replacing state."""
    try:
        from config import atomic_update_json

        def _update(state: dict) -> dict:
            positions = dict(state.get("open_positions") or {})
            snapshot = dict(positions.get(str(trade_id)) or {})
            snapshot.update({
                "exit_pending_reason": position_state.get("exit_pending_reason"),
                "exit_pending_since": position_state.get("exit_pending_since"),
                "exit_attempts": position_state.get("exit_attempts", 0),
            })
            positions[str(trade_id)] = snapshot
            return {**state, "open_positions": positions}

        atomic_update_json(get_bot_state_path(), _update)
    except Exception:
        logger.warning("exit latch persistence failed for trade %s", trade_id, exc_info=True)


def _clear_exit_latch(position_state: dict) -> None:
    """Clear a completed exit intent so it cannot fire again next tick."""
    position_state.pop("exit_pending_reason", None)
    position_state.pop("exit_pending_since", None)
    position_state["exit_attempts"] = 0


def _exit_latch_snapshot(position_state: dict) -> dict:
    """Fields that every persisted position snapshot must carry forward."""
    return {
        "exit_pending_reason": position_state.get("exit_pending_reason"),
        "exit_pending_since": position_state.get("exit_pending_since"),
        "exit_attempts": position_state.get("exit_attempts", 0),
    }


@decision
def _evaluate_reviewed_strategy_exit(
    trade: dict,
    entry_time: datetime | str | None,
    now_et: datetime,
    *,
    one_minute_bars: pd.DataFrame | None,
    five_minute_bars: pd.DataFrame | None,
    option_quote: dict | None = None,
    session_close: datetime | None = None,
    compression_bars_lookup=None,
) -> tuple[bool, str] | None:
    """Route a reviewed strategy to the exit policy its evidence declares."""
    from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile

    strategy_id = str(trade.get("strategy_id") or "").strip().upper()
    if session_close is not None:
        from datetime import timedelta
        from strategy_health.impulse_exit import et
        deadline = et(session_close) - timedelta(minutes=5)
        if entry_time is not None:
            deadline = min(deadline, et(entry_time).replace(hour=15, minute=55, second=0, microsecond=0))
        if et(now_et) >= deadline:
            return True, 'research_session_close'
    from config.research_order_specs import SPECS
    if strategy_id in SPECS:
        from trading.research_order_exit import evaluate_exit
        return evaluate_exit(trade, entry_time, now_et, one_minute_bars, option_quote,
                             session_close=session_close, compression_bars_lookup=compression_bars_lookup)
    if strategy_id == "V2_TREND_CONT":
        from trading.trend_continuation_research_exit import evaluate_exit

        return evaluate_exit(trade, entry_time, now_et, one_minute_bars, session_close=session_close)
    if not uses_v2_orb_execution_profile(strategy_id):
        return None
    if strategy_id == "CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG":
        from trading.vwap_displacement_exit import evaluate_vwap_displacement_exit

        return evaluate_vwap_displacement_exit(
            entry_time,
            now_et,
            one_minute_bars=one_minute_bars,
            five_minute_bars=five_minute_bars,
            strategy_context=trade.get("strategy_context_json"),
        )

    from trading.v2_orb_paper_exit import evaluate_v2_orb_paper_exit

    return evaluate_v2_orb_paper_exit(entry_time, now_et, strategy_id)


@position_cycle
def _manage_open_position(
    alpaca: "AlpacaClient",
    tradier: "TradierClient",
    trade: dict,
    balance: float,
) -> None:
    """
    Adaptive position manager — structure-driven exits, not time-driven.

    Called every tick for each open trade. Fetches both an option quote (for
    current P&L) and the underlying's 1-min bars (for structural analysis).
    All exit decisions are made against chart structure, not a clock.
    """
    _US        = get_user_state()
    _risk      = get_user_risk()
    _trade_log = get_user_trade_log()

    try:
        from config.research_order_specs import SPECS
        research_session_close = None
        from trading.research_session_clock import uses_broker_session
        if uses_broker_session(trade):
            from trading.research_session_clock import session_close_if_open
            research_session_close = session_close_if_open(alpaca, _now_et())
            if research_session_close is None:
                note('exit_check_skipped', {'reason':'broker_session_not_open_or_unverified'})
                return
        # Session expiry does not require a fresh mark.
        # Preserve the broker-session gate above and existing exit thresholds.
        if research_session_close is not None:
            from database.helpers import _to_et_datetime
            guard_now = _now_et()
            guard_entry = _to_et_datetime(trade.get('entry_time')) if trade.get('entry_time') else None
            guard_result = _evaluate_reviewed_strategy_exit(
                trade, guard_entry, guard_now, one_minute_bars=None,
                five_minute_bars=None, session_close=research_session_close,
            )
            guard_due, guard_reason = guard_result or (False, 'hold')
            # Only session expiry is unconditional here. Missing bars supplied
            # by this preflight must not activate a missing-structure fallback.
            if guard_reason != 'research_session_close':
                guard_due, guard_reason = False, 'hold'
            if guard_due:
                guard_state = _US.setdefault('positions', {}).setdefault(trade['id'], {})
                guard_due, guard_reason = _resolve_latched_exit(
                    guard_state, guard_due, guard_reason, guard_now,
                )
                guard_state['exit_attempts'] = int(guard_state.get('exit_attempts') or 0) + 1
                _persist_exit_latch(trade['id'], guard_state)
                from trading.position_manager.close import _close_position
                _close_position(alpaca, trade, float(trade['entry_price']), guard_reason)
                return

        if trade.get('strategy_id') in ('RESEARCH_FAILED_RANGE_V2', 'RESEARCH_QQQ_TREND_V2', 'V2_VWAP_PULLBACK'):
            from trading.research_order_exit import evaluate_exit
            deadline_now = _now_et()
            due, deadline_reason = traced_call('early_native_deadline', evaluate_exit,
                trade, trade.get('entry_time'), deadline_now, None,
                session_close=research_session_close,
            )
            if due and deadline_reason in {'research_failed_range_30m', 'research_qqq_trend_30m', 'research_session_close',
                                           'selected_test_30m', 'selected_test_60m', 'selected_test_90m', 'selected_test_120m'}:
                deadline_state = _US.setdefault('positions', {}).setdefault(trade['id'], {})
                _resolve_latched_exit(deadline_state, True, deadline_reason, deadline_now)
                deadline_state['exit_attempts'] = int(deadline_state.get('exit_attempts') or 0) + 1
                _persist_exit_latch(trade['id'], deadline_state)
                from trading.position_manager.close import _close_position
                _close_position(alpaca, trade, None, deadline_reason, pricing_unavailable=True)
                return
        if trade.get('strategy_id') == 'V2_TSLA_TWO_LEG_TREND_PULLBACK':
            from database.helpers import _to_et_datetime
            from trading.tsla_giveback_exit import evaluate_tsla_giveback
            deadline_now = _now_et()
            entry_at = _to_et_datetime(trade['entry_time']) if trade.get('entry_time') else None
            due, deadline_reason = _evaluate_reviewed_strategy_exit(
                trade, entry_at, deadline_now, one_minute_bars=None,
                five_minute_bars=None, session_close=research_session_close,
            )
            if not due:
                pending = evaluate_tsla_giveback(trade, entry_at, deadline_now, None)
                if pending is not None:
                    due, deadline_reason = pending
            deadline_state = _US.setdefault('positions', {}).setdefault(trade['id'], {})
            due, deadline_reason = _resolve_latched_exit(
                deadline_state, due, deadline_reason, deadline_now,
            )
            if due:
                deadline_state['exit_attempts'] = int(deadline_state.get('exit_attempts') or 0) + 1
                _persist_exit_latch(trade['id'], deadline_state)
                from trading.position_manager.close import _close_position
                _close_position(alpaca, trade, float(trade['entry_price']), deadline_reason)
                return

        # Full-exit intent and fixed deadlines survive missing quotes/bars.
        # Partial profit-taking stays on its quantity-aware path below.
        from trading.position_manager.exit_preflight import full_exit_reason, executable_quote
        preflight_now = _now_et()
        preflight_state = _US.setdefault('positions', {}).get(trade['id'], {})
        preflight_reason = traced_call('full_exit_preflight', full_exit_reason, trade, preflight_state, preflight_now)
        if preflight_reason:
            preflight_state = _US['positions'].setdefault(trade['id'], {})
            # A full deadline supersedes an unfinished partial profit take.
            preflight_state['exit_pending_reason'] = preflight_reason
            preflight_state.setdefault('exit_pending_since', preflight_now.isoformat())
            preflight_state['exit_attempts'] = int(preflight_state.get('exit_attempts') or 0) + 1
            _persist_exit_latch(trade['id'], preflight_state)
            exit_bid, exit_quote = executable_quote(tradier, trade['contract_symbol'])
            note('preflight_exit_price', {'bid':exit_bid,'quote':exit_quote,'reason':preflight_reason})
            from trading.position_manager.close import _close_position
            _close_position(alpaca, trade, exit_bid, preflight_reason,
                            bid_price=exit_bid, reference_quote=exit_quote,
                            pricing_unavailable=exit_bid is None)
            return
        quote = tradier.get_option_quote(trade["contract_symbol"])
        note('option_quote_received_by_manager',quote)
        alpaca_positions = alpaca.get_positions()
        alpaca_pos = next(
            (p for p in alpaca_positions if p.get("symbol") == trade["contract_symbol"]),
            None,
        )

        if alpaca_pos is not None and alpaca_pos.get("current_price") is not None:
            current_price = float(alpaca_pos["current_price"])
        elif quote is not None:
            current_price = quote["mid"]
            logger.warning(
                "%s not found in Alpaca positions — falling back to Tradier's "
                "quote for current_price (may not reflect Alpaca's real mark)",
                trade["contract_symbol"],
            )
        else:
            logger.warning("Cannot price %s — holding", trade["contract_symbol"])
            note('exit_check_skipped', {'reason':'pricing_unavailable'})
            return

        note('selected_option_mark', {'current_price':current_price,'basis':'broker_position' if alpaca_pos is not None and alpaca_pos.get('current_price') is not None else 'tradier_mid'})

        bid_price     = float(quote.get("bid") or current_price) if quote else current_price
        entry_price   = trade["entry_price"]
        trade_id      = trade["id"]
        ticker        = trade.get("ticker", "")
        option_type   = (trade.get("option_type") or "call").lower()
        direction     = "bullish" if option_type == "call" else "bearish"

        # One quote per minute while PAPER positions are open.  It gives the
        # research layer actual observed spread/MFE/MAE context without adding
        # any branch to live execution or any high-frequency DB load.
        if bool(trade.get("paper", True)) and quote is not None:
            try:
                from database import record_paper_option_quote
                record_paper_option_quote(
                    trade_id=trade_id,
                    contract_symbol=trade["contract_symbol"],
                    observation_kind="mark",
                    observed_at=_now_et(),
                    quote=quote,
                    source="tradier_quote",
                )
            except Exception:
                logger.warning("paper mark quote capture failed for trade %s", trade_id, exc_info=True)

        ps = _US["positions"].setdefault(trade_id, {
            "peak_price":                None,
            "min_price":                 None,
            "entry_time":                trade.get("entry_time"),
            "stage1_done":               False,
            "stage1_be_price":           None,
            "current_stop_pct":          _risk.ORB_STOP_PCT if _risk else 0.20,
            "struct_stop_price":         None,
            "current_option_price":      None,
            "current_option_price_time": None,
            "last_position_narration_minute": None,
            "atr_trail_stop":            None,
            "initial_atr_stop":          None,
            "vwap_breached_bars":        0,
            "vwap_5m_breached_bars":     0,
            "peak_underlying":           None,
            "last_bar_fetch_minute":     None,
            "cached_underlying_df":      None,
            "cached_5m_df":              None,
            "cached_15m_df":             None,
            "cached_1h_df":              None,
            "last_5m_fetch_key":         None,
            "last_15m_fetch_key":        None,
            "last_1h_fetch_key":         None,
        })

        ps["current_option_price"]      = current_price
        ps["current_option_price_time"] = _now_et().strftime("%H:%M:%S")
        from trading.recovery_state import restore_stage1
        restore_stage1(trade, ps)

        # Reviewed exits use the persisted entry clock, not post-order processing time.
        # Keep the original entry clock when a later partial fill updates entry_fill_time.
        entry_time_iso = (
            trade.get("entry_time") or ps.get("entry_time")
            if uses_broker_session(trade)
            else ps.get("entry_time") or trade.get("entry_time")
        )
        try:
            entry_time = datetime.fromisoformat(entry_time_iso) if entry_time_iso else None
            if entry_time is not None and entry_time.tzinfo is None:
                entry_time = _ET_TZ.localize(entry_time)
        except Exception:
            entry_time = None

        from risk import persist_peak_price, recover_peak_price
        if ps.get("peak_price") is None:
            ps["peak_price"] = recover_peak_price(trade_id) or entry_price
        if current_price > ps["peak_price"]:
            ps["peak_price"] = current_price
            persist_peak_price(trade_id, current_price)

        if ps.get("min_price") is None:
            ps["min_price"] = entry_price
        if current_price < ps["min_price"]:
            ps["min_price"] = current_price

        stage1_done     = bool(ps.get("stage1_done"))
        stage1_be_price = ps.get("stage1_be_price")
        now_et          = _now_et()

        _minute_key = now_et.strftime("%Y-%m-%d %H:%M")
        df_under: Optional[pd.DataFrame] = ps.get("cached_underlying_df")

        if ps.get("last_bar_fetch_minute") != _minute_key:
            try:
                from signals import bars_to_df
                _bars, _err, _ = alpaca.get_session_bars(ticker, "1Min")
                if _bars and not _err:
                    df_under = bars_to_df(_bars)
                    ps["cached_underlying_df"] = df_under
                    ps["last_bar_fetch_minute"] = _minute_key

                    _last_high = float(df_under["high"].iloc[-1])
                    _last_low  = float(df_under["low"].iloc[-1])
                    if direction == "bullish":
                        ps["peak_underlying"] = max(ps.get("peak_underlying") or _last_high, _last_high)
                    else:
                        ps["peak_underlying"] = min(ps.get("peak_underlying") or _last_low, _last_low)
            except Exception as _be:
                logger.debug("Bar fetch for position management failed (%s): %s", ticker, _be)

        _5m_bar_key = now_et.strftime("%Y-%m-%d %H:") + str(now_et.minute // 5)
        df_5m: Optional[pd.DataFrame] = ps.get("cached_5m_df")
        if ps.get("last_5m_fetch_key") != _5m_bar_key:
            try:
                from signals import bars_to_df as _btd
                _b5, _e5, _ = alpaca.get_session_bars(ticker, "5Min")
                if _b5 and not _e5:
                    df_5m = _btd(_b5)
                    ps["cached_5m_df"]      = df_5m
                    ps["last_5m_fetch_key"] = _5m_bar_key
            except Exception as _e5m:
                logger.debug("5m bar fetch failed (%s): %s", ticker, _e5m)

        _15m_bar_key = now_et.strftime("%Y-%m-%d %H:") + str(now_et.minute // 15)
        df_15m: Optional[pd.DataFrame] = ps.get("cached_15m_df")
        if ps.get("last_15m_fetch_key") != _15m_bar_key:
            try:
                from signals import bars_to_df as _btd
                _b15, _e15, _ = alpaca.get_session_bars(ticker, "15Min")
                if _b15 and not _e15:
                    df_15m = _btd(_b15)
                    ps["cached_15m_df"]      = df_15m
                    ps["last_15m_fetch_key"] = _15m_bar_key
            except Exception as _e15m:
                logger.debug("15m bar fetch failed (%s): %s", ticker, _e15m)

        _1h_bar_key = now_et.strftime("%Y-%m-%d %H")
        df_1h: Optional[pd.DataFrame] = ps.get("cached_1h_df")
        if ps.get("last_1h_fetch_key") != _1h_bar_key:
            try:
                from signals import bars_to_df as _btd
                _b1h, _e1h = alpaca.get_bars(ticker, "1Hour", limit=100)
                if _b1h and not _e1h:
                    df_1h = _btd(_b1h)
                    ps["cached_1h_df"]      = df_1h
                    ps["last_1h_fetch_key"] = _1h_bar_key
            except Exception as _e1h:
                logger.debug("1h bar fetch failed (%s): %s", ticker, _e1h)

        atr_trail_stop: Optional[float]  = ps.get("atr_trail_stop")
        vwap: Optional[float]            = None
        trend_dead: bool                 = False
        _rvol_for_exit: float            = 0.0

        _atr_target_price: Optional[float] = None
        _momentum_fading: bool             = False

        _trade_age_min = (
            (now_et - entry_time).total_seconds() / 60
            if entry_time else 999.0
        )

        _dynamic_trail_mult = _TRAIL_MULT_BASE
        _mtf_notes: list[str] = []

        _1h_bias = trend_bias_1h(df_1h, direction)
        if _1h_bias == "with":
            _dynamic_trail_mult = _TRAIL_MULT_1H_WITH
            _mtf_notes.append(f"1h_trend=WITH({_TRAIL_MULT_1H_WITH}×)")
        elif _1h_bias == "against":
            _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_1H_AGAINST)
            _mtf_notes.append(f"1h_trend=AGAINST({_TRAIL_MULT_1H_AGAINST}×)")

        if df_5m is not None and not df_5m.empty:
            _5m_rsi = compute_rsi(df_5m)
            _rsi_exhausted = (
                (_5m_rsi is not None and direction == "bullish" and _5m_rsi >= _RSI_EXHAUST_CALL) or
                (_5m_rsi is not None and direction == "bearish" and _5m_rsi <= _RSI_EXHAUST_PUT)
            )
            if _rsi_exhausted:
                _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_TIGHT)
                _mtf_notes.append(f"5m_rsi_exhaust={_5m_rsi:.0f}({_TRAIL_MULT_TIGHT}×)")

            _macd_hist = compute_macd_hist(df_5m)
            _macd_fading = len(_macd_hist) >= _MACD_FADE_BARS and all(
                _macd_hist[-(i + 1)] < _macd_hist[-(i + 2)]
                for i in range(_MACD_FADE_BARS - 1)
            )
            if _macd_fading:
                _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_1H_AGAINST)
                _mtf_notes.append(f"5m_macd_fade({_TRAIL_MULT_1H_AGAINST}×)")

            _momentum_fading = (
                (_rsi_exhausted and _macd_fading) if (_risk and _risk.STAGE1_MOMENTUM_REQUIRE_BOTH)
                else (_rsi_exhausted or _macd_fading)
            )

            _5m_vwap = _compute_vwap(df_5m)
            _5m_close = float(df_5m["close"].iloc[-1])
            if _5m_vwap is not None:
                _5m_breached = (
                    (direction == "bullish" and _5m_close < _5m_vwap) or
                    (direction == "bearish" and _5m_close > _5m_vwap)
                )
                if _5m_breached:
                    ps["vwap_5m_breached_bars"] = ps.get("vwap_5m_breached_bars", 0) + 1
                else:
                    ps["vwap_5m_breached_bars"] = 0

        if df_15m is not None and not df_15m.empty:
            _15m_close = float(df_15m["close"].iloc[-1])
            _swing_15m = _structural_swing_stop(df_15m, direction, lookback=20)
            if _swing_15m is not None and _15m_close > 0:
                _prox_pct = abs(_15m_close - _swing_15m) / _15m_close
                if _prox_pct <= _15M_SWING_PROX_PCT:
                    _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_TIGHT)
                    _mtf_notes.append(f"near_15m_swing={_prox_pct*100:.2f}%({_TRAIL_MULT_TIGHT}×)")

        if _mtf_notes:
            logger.debug("[%s] MTF trail mult=%.1f× — %s", ticker, _dynamic_trail_mult, " | ".join(_mtf_notes))

        if df_under is not None and not df_under.empty:
            _underlying_now = float(df_under["close"].iloc[-1])

            _atr = _compute_atr(df_5m) if (df_5m is not None and len(df_5m) >= 15) else _compute_atr(df_under)

            if _atr is not None and _risk:
                _raw_target_price = entry_price + _risk.STAGE1_ATR_TARGET_MULT * _atr * _DELTA_APPROX
                _min_target_price = entry_price * (1.0 + _risk.STAGE1_TARGET_MIN_PCT)
                _atr_target_price = max(_raw_target_price, _min_target_price)

            if _atr is not None and ps.get("initial_atr_stop") is None:
                _init_mult    = 2.5
                _atr_opt_stop = entry_price - _init_mult * _atr * _DELTA_APPROX
                ps["initial_atr_stop"] = round(
                    max(entry_price * 0.70, min(entry_price * 0.85, _atr_opt_stop)), 4
                )
                logger.info(
                    "[%s] Initial ATR stop set: ATR=%.4f × %.1f× → opt_stop=%.4f (final=%.4f, bounds=[%.4f, %.4f])",
                    ticker, _atr, _init_mult, _atr_opt_stop,
                    ps["initial_atr_stop"], entry_price * 0.70, entry_price * 0.85,
                )

            _opt_gain_pct = (current_price - entry_price) / entry_price if entry_price else 0.0
            _trail_profit_gate = _opt_gain_pct >= 0.15
            if (_atr is not None
                    and ps.get("peak_underlying") is not None
                    and _trade_age_min >= _MIN_TRAIL_WARMUP_MIN
                    and _trail_profit_gate):
                _peak_u = float(ps["peak_underlying"])
                if direction == "bullish":
                    _atr_stop_u = _peak_u - _dynamic_trail_mult * _atr
                else:
                    _atr_stop_u = _peak_u + _dynamic_trail_mult * _atr

                _atr_stop_opt = _underlying_stop_to_option(
                    entry_price, _underlying_now, _atr_stop_u
                )

                _swing_u = _structural_swing_stop(df_under, direction)
                if _swing_u is not None:
                    _swing_opt = _underlying_stop_to_option(
                        entry_price, _underlying_now, _swing_u
                    )
                    if direction == "bullish":
                        _new_trail = max(_atr_stop_opt, _swing_opt)
                    else:
                        _new_trail = max(_atr_stop_opt, _swing_opt)
                else:
                    _new_trail = _atr_stop_opt

                if atr_trail_stop is None or _new_trail > atr_trail_stop:
                    atr_trail_stop = _new_trail
                    ps["atr_trail_stop"] = atr_trail_stop

            try:
                if df_5m is not None and len(df_5m) >= 5:
                    _v5       = df_5m["volume"].astype(float)
                    _curr_vol = float(_v5.iloc[-1])
                    _base_vol = float(_v5.iloc[-5:-1].median())
                else:
                    _curr_vol = float(df_under["volume"].iloc[-1])
                    _base_vol = float(df_under["volume"].iloc[-20:].mean()) if len(df_under) >= 5 else _curr_vol
                _rvol_for_exit = _curr_vol / _base_vol if _base_vol > 0 else 0.0
            except Exception:
                _rvol_for_exit = 0.0

            vwap = _compute_vwap(df_under)

            if vwap is not None:
                _vwap_breached_now = (
                    (direction == "bullish" and _underlying_now < vwap) or
                    (direction == "bearish" and _underlying_now > vwap)
                )
                if _vwap_breached_now:
                    ps["vwap_breached_bars"] = ps.get("vwap_breached_bars", 0) + 1
                else:
                    ps["vwap_breached_bars"] = 0

            _vwap_breached = (
                ps.get("vwap_5m_breached_bars", 0) >= _VWAP_5M_BREACH_BARS
                if df_5m is not None
                else ps.get("vwap_breached_bars", 0) >= _VWAP_BREACH_BARS
            )
            if _vwap_breached:
                _df_for_trend = df_5m if (df_5m is not None and len(df_5m) >= 55) else df_under
                _adx    = compute_adx(_df_for_trend)
                _ema_ok = ema_stack_aligned(_df_for_trend, direction)
                adx_weak   = (_adx is not None and _adx < _ADX_WEAK_THRESHOLD)
                ema_broken = not _ema_ok
                trend_dead = adx_weak and ema_broken

        _current_stop_pct_display = (
            round(1.0 - atr_trail_stop / entry_price, 4) if atr_trail_stop else
            (_risk.ORB_STOP_PCT if _risk else 0.20)
        )
        ps["current_stop_pct"] = _current_stop_pct_display

        _state_path_m = get_bot_state_path()
        try:
            from config import atomic_update_json
            _position_snapshot = {
                "trade_id":                  trade_id,
                "contract_symbol":           trade.get("contract_symbol"),
                "ticker":                    ticker,
                "option_type":               option_type,
                "entry_price":               entry_price,
                "contracts":                 trade.get("contracts"),
                "current_stop_pct":          _current_stop_pct_display,
                "current_option_price":      current_price,
                "current_option_price_time": ps["current_option_price_time"],
                "stage1_done":               stage1_done,
                "peak_price":                ps["peak_price"],
                "min_price":                 ps.get("min_price"),
                "entry_time":                entry_time_iso,
                "atr_trail_stop":            atr_trail_stop,
                "initial_atr_stop":          ps.get("initial_atr_stop"),
                "vwap_breached_bars":        ps.get("vwap_breached_bars", 0),
                "trend_dead":                trend_dead,
                # Preserve a triggered close across normal mark snapshots and
                # process restarts until Alpaca confirms the position closed.
                **_exit_latch_snapshot(ps),
            }
            def _update_position_state(state: dict) -> dict:
                positions = dict(state.get("open_positions") or {})
                positions[str(trade_id)] = _position_snapshot
                return {
                    **state,
                    "open_positions": positions,
                    "current_stop_pct": _current_stop_pct_display,
                    "current_option_price": current_price,
                    "current_option_price_time": ps["current_option_price_time"],
                    "session_pnl": _US.get("session_pnl", 0.0),
                }
            atomic_update_json(_state_path_m, _update_position_state)
        except Exception:
            pass

        _struct_stop = ps.get("struct_stop_price")

        if ps.get("last_position_narration_minute") != _minute_key:
            from database import log_event
            ps["last_position_narration_minute"] = _minute_key
            _contracts  = trade.get("contracts", 1)
            _pnl_now    = (current_price - entry_price) * _contracts * 100
            _pnl_pct    = (current_price - entry_price) / entry_price * 100 if entry_price else 0.0
            _stop_desc  = f"${atr_trail_stop:.2f} (ATR/swing trail)" if atr_trail_stop else f"{_current_stop_pct_display*100:.0f}% below entry"
            _stage_desc = "Stage 2 — runner, trail active" if stage1_done else "Stage 1 — full size"
            _vwap_desc  = ""
            if ps.get("vwap_breached_bars", 0) >= _VWAP_BREACH_BARS:
                _vwap_desc = f" ⚠️ VWAP breach {ps['vwap_breached_bars']}bar — trend_dead={trend_dead}."
            from trading.diagnostics.exit_policy import reviewed_exit_description
            _policy_desc = reviewed_exit_description(trade, ps, now_et)
            if _policy_desc is None:
                _policy_desc = f"Calculated reference {_stop_desc}. See Protection status for verified active levels. {_stage_desc}.{_vwap_desc}"
            log_event(
                "INFO", "position_update",
                f"🟡 [{trade['contract_symbol']}] Holding — "
                f"option @ ${current_price:.2f} (entry ${entry_price:.2f}, peak ${ps['peak_price']:.2f}). "
                f"P&L {'+' if _pnl_now >= 0 else ''}${_pnl_now:.2f} ({_pnl_pct:+.1f}%). "
                f"{_policy_desc}"
            )

        _vwap_breached_any = (
            ps.get("vwap_5m_breached_bars", 0) >= 1
            if df_5m is not None
            else ps.get("vwap_breached_bars", 0) >= 1
        )

        _trail_is_armed     = atr_trail_stop is not None
        _effective_atr_stop = atr_trail_stop or ps.get("initial_atr_stop")

        from config import get_settings as _gs_exit
        _simplified_mode = bool(_gs_exit().get("simplified_exit_mode", True))
        _atr_for_exit        = locals().get("_atr")
        _underlying_for_exit = locals().get("_underlying_now")
        # Reviewed strategies use their evidence-matched exit rather than the
        # generic adaptive manager. Most use a locked hold; VWAP Displacement
        # owns the structural prior-high/VWAP/EOD policy below. This branch
        # does not change strategy authorization or enable live trading.
        from trading.v2_orb_execution_profile import uses_v2_orb_execution_profile
        _is_v2_orb = uses_v2_orb_execution_profile(trade.get("strategy_id"))
        def compression_bars_lookup():
            if ps.get('compression_repair_minute') != _minute_key:
                ps['compression_repair_minute'] = _minute_key
                ps['compression_repair_frame'] = pd.DataFrame()
                bars, error, _ = tradier.get_session_bars(ticker, '1Min')
                if bars and not error:
                    from signals import bars_to_df
                    ps['compression_repair_frame'] = bars_to_df(bars)
            result = ps.get('compression_repair_frame', pd.DataFrame())
            note('compression_bars_lookup_result',result)
            return result
        _reviewed_exit = _evaluate_reviewed_strategy_exit(
            trade,
            entry_time,
            now_et,
            one_minute_bars=df_under,
            five_minute_bars=df_5m,
            option_quote=quote,
            session_close=research_session_close,
            compression_bars_lookup=compression_bars_lookup,
        )
        if _reviewed_exit is not None:
            _risk_branch = 'reviewed'
            should_exit, reason = _reviewed_exit
            if not should_exit:
                from trading.tsla_giveback_exit import evaluate_tsla_giveback
                _giveback_exit = evaluate_tsla_giveback(
                    trade, entry_time, now_et, quote,
                )
                if _giveback_exit is not None:
                    should_exit, reason = _giveback_exit
        elif _simplified_mode and _atr_for_exit is not None and _underlying_for_exit is not None:
            _risk_branch = 'simplified'
            from trading.simplified_exit_live import evaluate_simplified_live_exit
            should_exit, reason = traced_call('simplified_exit', evaluate_simplified_live_exit,
                ps, entry_price, current_price,
                entry_time=entry_time, now=now_et, direction=direction,
                atr=_atr_for_exit, underlying_now=_underlying_for_exit,
            )
        else:
            _risk_branch = 'adaptive'
            should_exit, reason = traced_call('adaptive_risk_exit', _risk.should_exit,
                entry_price, current_price,
                entry_time      = entry_time,
                now             = now_et,
                stage1_done     = stage1_done,
                stage1_be_price = stage1_be_price,
                peak_price      = ps.get("peak_price"),
                struct_stop_price = _struct_stop,
                atr_trail_stop  = _effective_atr_stop,
                trail_armed     = _trail_is_armed,
                vwap            = vwap,
                vwap_breached   = _vwap_breached_any,
                trend_dead      = trend_dead,
                direction       = direction,
                rvol            = _rvol_for_exit,
                atr_target_price = _atr_target_price,
                momentum_fading  = _momentum_fading,
            )

        # Supplemental approved paper exit. Native and safety exits have priority.
        if not should_exit:
            from trading.premium_policy import evaluate_position
            should_exit, reason = evaluate_position(trade, quote, now_et)

        # Classification follows the selected branch; it never selects an exit.
        # Persist separately so a display failure cannot interrupt protection.
        try:
            from risk.protection import classify_risk_levels, monitored_risk_fields, monitoring_failure
            _fields = list(monitored_risk_fields(trade, branch=_risk_branch))
            if _risk_branch == 'adaptive':
                _fields = [f for f in _fields if f != ('initial_atr_stop' if atr_trail_stop else 'atr_trail_stop')]
                if not stage1_done:
                    _fields = [f for f in _fields if f != 'stage1_be_price']
            if _risk_branch == 'simplified':
                _fields = [f for f in _fields if f != ('initial_atr_stop' if ps.get('struct_stop_price') else 'struct_stop_price')]
            _inventory = classify_risk_levels(
                trade, position=ps, monitored_fields=_fields,
                monitoring_reason=monitoring_failure(now=now_et, quote=quote, frame=df_under, reason=reason))
            _inventory['observed_at'] = now_et.isoformat()
            _inventory['execution_branch'] = _risk_branch
            ps['risk_classification'] = _inventory
            def _write_risk_inventory(state):
                positions = dict(state.get('open_positions') or {})
                item = dict(positions.get(str(trade_id)) or {})
                item['risk_classification'] = _inventory
                positions[str(trade_id)] = item
                return dict(state, open_positions=positions)
            atomic_update_json(_state_path_m, _write_risk_inventory)
        except Exception:
            logger.warning('risk_classification_unavailable trade=%s', trade_id, exc_info=True)
        should_exit, reason = _resolve_latched_exit(ps, should_exit, reason, now_et)

        if not should_exit:
            return

        ps["exit_attempts"] = int(ps.get("exit_attempts") or 0) + 1
        _persist_exit_latch(trade_id, ps)

        # NOTE: AI reasoning narration for this exit decision does NOT fire
        # here anymore. narrate_exit() fires ONLY after a close_trade() call
        # actually confirms — see close.py — a slow/rejected/retried close
        # order used to re-trigger narration on every following tick.

        if reason.startswith("stage1"):
            half_contracts = max(1, trade["contracts"] // 2)
            if reason == 'stage1_research_atr10':
                from trading.research_order_exit import partial_remaining
                half_contracts = min(int(trade['contracts']), partial_remaining(trade))
                if half_contracts <= 0:
                    _clear_exit_latch(ps)
                    _persist_exit_latch(trade_id, ps)
                    return
            from database import log_event

            if half_contracts >= trade["contracts"]:
                log_event(
                    "INFO", "trading_logic",
                    f"🟢 [{trade['ticker']}] +50% target hit — only "
                    f"{trade['contracts']} contract(s) held, taking full exit "
                    f"(can't split a single contract). Closing now.",
                )
                from trading.position_manager.close import _close_position
                _close_position(alpaca, trade, current_price,
                                f"{reason.split(' ')[0]}_full_exit_single_contract",
                                bid_price=bid_price, mtf_notes=_mtf_notes,
                                reference_quote=quote)
                return

            from config import get_settings
            settings = get_settings()
            paper    = settings.get("paper_trading", True)

            if paper:
                _trade_log.info(
                    "stage1_partial_exit",
                    extra={
                        "event":          "stage1_partial_exit",
                        "contracts_sold": half_contracts,
                        "exit_price":     round(current_price, 4),
                        "entry_price":    round(entry_price, 4),
                    },
                )
            from trading.position_manager.helpers import _snapshot_exit_annotations
            fill = exit_order(alpaca.place_option_order, trade,
                symbol          = trade["contract_symbol"],
                qty             = half_contracts,
                side            = "sell",
                order_type      = "limit",
                limit_price     = bid_price if reason == 'stage1_research_atr10' else current_price,
                step_to_price   = None if reason == 'stage1_research_atr10' else bid_price,
                allow_market_fallback = False,
                position_intent = "sell_to_close",
                order_context   = {
                    "ticker": trade.get("ticker"),
                    "strategy_id": trade.get("strategy_id"),
                    "trade_id": trade.get("id"),
                    "expected_contracts": trade["contracts"],
                    "exit_reason": f"{reason.split(' ')[0]}_profit_take",
                    "exit_annotations": _snapshot_exit_annotations(trade.get("ticker", "")),
                    "peak_price": ps.get("peak_price"),
                    "mae_price": ps.get("min_price"),
                },
            )

            if fill is None:
                if _reconcile_if_phantom(alpaca, trade):
                    return
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take order "
                    f"did not fill — leaving at full size, will retry next tick.",
                )
                return

            fill_price = float(fill.get("confirmed_fill_price") or fill.get("filled_avg_price") or current_price)

            _sold_qty = int(fill.get("filled_qty", half_contracts))
            if _sold_qty > half_contracts:
                _sold_qty = half_contracts
            if _sold_qty != half_contracts:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take only sold "
                    f"{_sold_qty} of {half_contracts} intended contract(s) — "
                    f"recording the REAL sold size.",
                )
                logger.warning(
                    "partial_fill_stage1: trade_id=%s requested=%d filled=%d",
                    trade["id"], half_contracts, _sold_qty,
                )
            if _sold_qty < 1:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take reported "
                    f"filled but 0 contracts actually sold — leaving position at "
                    f"full size, will retry next tick.",
                )
                return

            from database import insert_trade, close_trade, get_conn
            from trading.position_manager.helpers import _snapshot_exit_annotations
            partial_id = fill.get("accounted_trade_id") or insert_trade(
                ticker          = trade["ticker"],
                contract_symbol = trade["contract_symbol"],
                option_type     = trade["option_type"],
                strike          = trade["strike"],
                expiry          = trade["expiry"],
                contracts       = _sold_qty,
                entry_price     = entry_price,
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
            partial_pnl = fill["accounted_pnl"] if fill.get("accounted_trade_id") else close_trade(
                trade_id             = partial_id,
                exit_price           = fill_price,
                exit_time            = _now_et().replace(tzinfo=None),
                exit_reason          = f"{reason.split(' ')[0]}_profit_take",
                confirmed_fill_price = fill_price,
                paper                = paper,
                annotations_json     = _snapshot_exit_annotations(trade.get("ticker", "")),
                exit_order_id        = str(fill.get("id") or "") or None,
                exit_fill_time       = fill.get("filled_at") or _now_et(),
            )
            try:
                from database import link_broker_order_to_trade
                link_broker_order_to_trade(
                    str(fill.get("id") or ""), partial_id, link_kind="stage-1 exit",
                )
            except Exception:
                logger.warning("stage-1 order-flow link failed for trade %s", partial_id, exc_info=True)

            if not fill.get("accounted_trade_id"):
                with get_conn() as _conn:
                    _conn.execute(
                        "UPDATE trades SET contracts = ? WHERE id = ?",
                        (trade["contracts"] - _sold_qty, trade["id"]),
                    )

            log_event(
                "INFO", "trading_logic",
                f"🟢 Took 50% profit — sold {_sold_qty} contract"
                f"{'s' if _sold_qty != 1 else ''} at ${fill_price:.2f} "
                f"(+${partial_pnl:.2f}). ATR/swing trailing stop now active on remainder.",
            )

            try:
                from ai_reasoning.narrator import narrate_exit
                _elapsed_min = (
                    (now_et - entry_time).total_seconds() / 60 if entry_time else 0.0
                )
                narrate_exit(
                    ticker           = ticker,
                    trade_id         = partial_id,
                    contract_symbol  = trade["contract_symbol"],
                    strategy_id      = trade.get("strategy_id"),
                    direction        = direction,
                    reason           = reason,
                    entry_price      = entry_price,
                    current_price    = fill_price,
                    elapsed_minutes  = _elapsed_min,
                    mtf_notes        = _mtf_notes,
                    peak_price       = ps.get("peak_price"),
                    min_price        = ps.get("min_price"),
                )
            except Exception as _ai_ex:
                logger.debug("ai_reasoning narrate_exit dispatch failed (non-fatal): %s", _ai_ex)

            from config import STAGE2_TRAIL_PCT
            ps["stage1_done"]     = reason != 'stage1_research_atr10' or _sold_qty >= half_contracts
            ps["stage1_be_price"] = None if reason == 'stage1_research_atr10' else round(entry_price * (1.0 + STAGE2_TRAIL_PCT), 4)
            # Stage 1 is a partial profit-take, not an instruction to liquidate
            # the runner.  Once that fill is confirmed, retire its sticky exit
            # intent and let Stage 2 evaluate the remaining contracts normally.
            _clear_exit_latch(ps)
            if reason == 'stage1_research_atr10' and _sold_qty < half_contracts:
                _resolve_latched_exit(ps, True, reason, now_et)
            _persist_exit_latch(trade["id"], ps)

        else:
            from trading.position_manager.close import _close_position
            # The V2 paper cohort must close at the observable bid, matching
            # the paid ask-to-bid markout.  Other strategies retain their
            # normal midpoint-then-bid execution attempt.
            from trading.v2_orb_paper_execution import exit_limit_prices
            _exit_limit, _exit_step = exit_limit_prices(
                bid=bid_price, midpoint=current_price,
                v2_paper_pilot=_is_v2_orb,
            )
            _close_position(alpaca, trade, _exit_limit, reason,
                             bid_price=_exit_step, mtf_notes=_mtf_notes,
                             reference_quote=quote)

    except Exception as e:
        note('manager_error', {'error_type':type(e).__name__,'reason':'manager_retry_next_tick'})
        from database import log_event
        logger.error("Error managing position: %s", e)
        log_event("ERROR", "trading_logic",
                  f"🔴 Error monitoring position: {type(e).__name__}. "
                  f"Will retry next tick. ({e})")
