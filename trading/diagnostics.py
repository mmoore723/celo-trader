"""
trading/diagnostics.py — Per-tick health checks and bar narrative logging.

Functions:
  _log_bar_thinking     — emit one human-readable audit log entry per 1-min bar
  _check_ghost_positions — detect/adopt Alpaca positions not tracked in the DB
  _sweep_orphaned_orders — cancel resting orders not tied to any open trade
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from trading.state import LIVE_STATE, _now_et

logger = logging.getLogger("celo_trader.trading_logic")

# Module-level flag so _check_ghost_positions only alerts ONCE per ghost event
_ghost_alert_logged = False


def _log_bar_thinking(df1m: "pd.DataFrame", df5: "pd.DataFrame", ticker: str) -> None:
    """
    Emit one detailed human-readable audit log entry per newly closed 1-min candle.

    Two modes:
      • IN TRADE  — narrates live position: P&L, stop distance, Stage 1 target,
                    time-box countdown, momentum check.
      • SCANNING  — gate-by-gate ORB checklist: price vs. OR levels, RVOL, VWAP,
                    what's passing, what's missing, what happens next.

    df1m — today's 1-min bars (timing, current price)
    df5  — augmented multi-day 5-min bars (RVOL baseline, ORB range)
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
        from database import log_event

        # ── Isolate today's 1-min bars ────────────────────────────────────────
        latest_date = df1m["time"].dt.date.max()
        today_1m    = df1m[df1m["time"].dt.date == latest_date].reset_index(drop=True)
        if len(today_1m) < 2:
            return

        last_bar     = today_1m.iloc[-1]
        bar_time_str = str(last_bar["time"])

        # Guard: already emitted this exact 1-min bar
        if LIVE_STATE.get("last_logged_1m_bar_time") == bar_time_str:
            return
        LIVE_STATE["last_logged_1m_bar_time"] = bar_time_str

        close = float(last_bar["close"])
        bar_t = bar_time_str[11:16]   # "HH:MM"

        # ── 5-min today slice (ORB detection uses 5-min bars) ─────────────────
        latest_date_5m = df5["time"].dt.date.max()
        today_df       = df5[df5["time"].dt.date == latest_date_5m].reset_index(drop=True)

        # ── VWAP (on today's 1-min bars for precision) ─────────────────────────
        try:
            vwap_series = _cvwap(today_1m)
            vwap_val    = float(vwap_series.iloc[-1]) if not _pd.isna(vwap_series.iloc[-1]) else None
        except Exception:
            vwap_val = None

        # ── RVOL (augmented df gives 10-day baseline) ─────────────────────────
        try:
            rvol_series = _crvol(df5, lookback_days=10)
            rvol_today  = rvol_series.reindex(today_df.index)
            rvol_val    = float(rvol_today.iloc[-1]) if (not rvol_today.empty and not _pd.isna(rvol_today.iloc[-1])) else 0.0
        except Exception:
            rvol_val = 0.0

        # ── Opening Range ─────────────────────────────────────────────────────
        or_info = _get_or(today_df)

        # ─────────────────────────────────────────────────────────────────────
        # BRANCH A: IN A TRADE on this ticker — narrate the live position
        # ─────────────────────────────────────────────────────────────────────
        _all_open = LIVE_STATE.get("open_trades") or []
        _ticker_trade = next(
            (t for t in _all_open
             if t.get("ticker") == ticker
             and t.get("strategy_id") != "RECOVERED_UNTRACKED"),
            None,
        )

        if _ticker_trade:
            _tid         = _ticker_trade.get("id")
            _pos_state   = LIVE_STATE.get("positions", {}).get(_tid, {})
            _entry_px    = float(_ticker_trade.get("entry_price") or 0)
            _opt_type    = (_ticker_trade.get("option_type") or "call").upper()
            _n_contracts = int(_ticker_trade.get("contracts") or 1)
            _strategy    = _ticker_trade.get("strategy_id", "INST_ORB")
            _stage1_done = _pos_state.get("stage1_done", LIVE_STATE.get("stage1_done", False))
            _stop_pct    = float(_pos_state.get("current_stop_pct") or 0.20)

            # Option price — use the last-known value from per-position state
            _cur_opt = float(
                _pos_state.get("current_option_price")
                or LIVE_STATE.get("current_option_price")
                or _entry_px
            )
            _pnl_pct  = ((_cur_opt - _entry_px) / _entry_px * 100) if _entry_px > 0 else 0.0
            _pnl_usd  = (_cur_opt - _entry_px) * _n_contracts * 100
            _sign     = "+" if _pnl_usd >= 0 else ""
            _pnl_emoji = "🟢" if _pnl_usd >= 0 else "🔴"

            # Stop levels
            _stop_px      = round(_entry_px * (1.0 - _stop_pct), 2)
            _cushion      = round(_cur_opt - _stop_px, 2)
            _pct_to_stop  = round((_cur_opt - _stop_px) / _cur_opt * 100, 1) if _cur_opt > 0 else 0

            # Stage 1 target (100% gain at 1×R)
            _s1_tgt = round(_entry_px * 1.50, 2)    # default 50% gain
            try:
                from trading.entry import _risk as _ar
                if _ar:
                    _s1_tgt = round(_ar.stage1_exit_price(_entry_px), 2)
            except Exception:
                pass
            _s1_dist = round(_s1_tgt - _cur_opt, 2)

            # Structural stop if set
            _struct_stop = _pos_state.get("struct_stop_price")
            _struct_note = f" | Structural stop ${_struct_stop:.2f}" if _struct_stop else ""

            # Time-box countdown
            _entry_time_str = str(_ticker_trade.get("entry_time", ""))
            _time_used = 0
            try:
                _et_now_tb = _now_et()
                _entry_ts  = _pd.Timestamp(_entry_time_str)
                _entry_naive = _entry_ts.tz_localize(None) if _entry_ts.tzinfo else _entry_ts.replace(tzinfo=None)
                _now_naive   = _et_now_tb.replace(tzinfo=None)
                _time_used   = max(0, int((_now_naive - _entry_naive).total_seconds() / 60))
            except Exception:
                pass
            _timebox   = 90 if _stage1_done else 45
            _time_left = max(0, _timebox - _time_used)
            _time_pressure = " ⚠️ EXIT SOON" if _time_left <= 5 else ""

            # Stage status
            if _stage1_done:
                _stage_note = "Stage 1 HIT ✅ — running runners to Stage 2 target"
            elif _s1_dist <= 0:
                _stage_note = f"Stage 1 target ${_s1_tgt:.2f} — REACHED 🎯"
            else:
                _stage_note = (
                    f"Stage 1 target ${_s1_tgt:.2f} — "
                    f"need ${abs(_s1_dist):.2f} more ({'+' if _s1_dist < 0 else ''}{abs(round(_s1_dist/_entry_px*100,1))}%)"
                )

            # Momentum
            _mom = (
                f"RVOL {rvol_val:.1f}× — {'momentum holding 💪' if rvol_val >= 1.2 else 'volume fading ⚠️ watch for reversal'}"
            )

            # Strategy name
            _sname = {
                "INST_ORB": "Opening Range Breakout", "VWAP_PB": "VWAP Pullback",
                "BOS_MSS": "Break of Structure",       "FVG": "Fair Value Gap",
                "CHAN_BREAK": "Channel Breakout",       "MID_BRK": "Mid-Day Breakdown",
                "TREND_CONT": "Trend Continuation",
            }.get(_strategy, _strategy)

            # Throttle: once per minute per position
            _last_min = _pos_state.get("last_position_narration_minute")
            if _last_min == bar_t:
                return
            if _tid and _tid in LIVE_STATE.get("positions", {}):
                LIVE_STATE["positions"][_tid]["last_position_narration_minute"] = bar_t

            # Position zone descriptor
            if _cushion > _entry_px * 0.10:
                _zone = "🟢 comfortable profit zone"
            elif _pnl_usd > 0:
                _zone = "🟡 in profit — stop is below entry, protected"
            elif _cushion < _entry_px * 0.05:
                _zone = "🔴 near stop — watch closely"
            else:
                _zone = "🟡 in drawdown — stop holding"

            narrative = (
                f"{_pnl_emoji} [{ticker}] {bar_t} — POSITION LIVE | "
                f"{_opt_type} @ ${_entry_px:.2f} × {_n_contracts}ct ({_sname}) | "
                f"Stock ${close:.2f} · Option ${_cur_opt:.2f} "
                f"({_sign}{_pnl_pct:.1f}% · {_sign}${abs(_pnl_usd):.0f}) {_zone} | "
                f"Stop ${_stop_px:.2f} ({_stop_pct*100:.0f}% stop · ${_cushion:.2f} cushion · "
                f"{_pct_to_stop:.1f}% above stop){_struct_note} | "
                f"{_stage_note} | "
                f"Time-box {_time_used}/{_timebox} min — {_time_left} min left{_time_pressure} | "
                f"{_mom}"
            )
            log_event("INFO", "bar_eval", narrative)
            return

        # ─────────────────────────────────────────────────────────────────────
        # BRANCH B: NOT IN A TRADE — gate-by-gate scanning narration
        # ─────────────────────────────────────────────────────────────────────
        if or_info is None:
            _rvol_pre = f"RVOL {rvol_val:.1f}× — {'active pre-market ✅' if rvol_val >= 1.5 else 'quiet so far'}"
            log_event("INFO", "bar_eval",
                      f"🟡 [{ticker}] {bar_t} — Pre-open: price ${close:.2f}. "
                      f"Waiting for 9:30 ET to close the first candle and set the Opening Range. "
                      f"{_rvol_pre}. No setup until OR is established.")
            return

        or_high  = or_info["high"]
        or_low   = or_info["low"]
        or_range = round(or_high - or_low, 2)

        # Gate evaluations
        rvol_ok    = rvol_val >= _ORB_RVOL
        vwap_str   = f"${vwap_val:.2f}" if vwap_val else "N/A"
        vwap_above = vwap_val is not None and close > vwap_val
        vwap_below = vwap_val is not None and close < vwap_val

        rvol_label = (
            f"RVOL {rvol_val:.1f}× ✅ (above {_ORB_RVOL:.1f}× threshold)"
            if rvol_ok else
            f"RVOL {rvol_val:.1f}× ❌ (need ≥{_ORB_RVOL:.1f}× — volume still thin)"
        )

        # VWAP relationship description
        if vwap_val:
            _vwap_delta = round(abs(close - vwap_val), 2)
            if vwap_above:
                vwap_label = (
                    f"VWAP ${vwap_val:.2f} ✅ price is ${_vwap_delta:.2f} ABOVE "
                    f"(buyers dominating — supports CALL)"
                )
            elif vwap_below:
                vwap_label = (
                    f"VWAP ${vwap_val:.2f} ✅ price is ${_vwap_delta:.2f} BELOW "
                    f"(sellers dominating — supports PUT)"
                )
            else:
                vwap_label = f"VWAP ${vwap_val:.2f} — price at VWAP (neutral, no clear bias)"
        else:
            vwap_label = "VWAP N/A (not enough bars yet)"

        # ── Price location relative to OR ─────────────────────────────────────
        if close > or_high:
            ext      = round(close - or_high, 2)
            vwap_ok  = vwap_above
            n_passed = sum([rvol_ok, vwap_ok])

            if n_passed == 2:
                conclusion = (
                    f"🔥 ALL 3 ORB GATES MET — evaluating CALL entry this bar. "
                    f"If filled: stop would be at OR LOW ${or_low:.2f}, "
                    f"Stage 1 target ~${round(close * 1.01, 2):.2f} (1% above entry)."
                )
            elif not rvol_ok and not vwap_ok:
                conclusion = (
                    f"⏳ Price broke out but BOTH volume and VWAP alignment are missing. "
                    f"Low-volume breakouts above VWAP are unreliable — bot is waiting. "
                    f"Need RVOL ≥{_ORB_RVOL:.1f}× AND price to hold above VWAP {vwap_str}."
                )
            elif not rvol_ok:
                conclusion = (
                    f"⏳ Price broke above OR but volume too thin ({rvol_val:.1f}×). "
                    f"A breakout without volume usually reverses — "
                    f"waiting for buying pressure to confirm before CALL entry."
                )
            else:
                conclusion = (
                    f"⏳ Volume confirms the breakout but VWAP alignment missing "
                    f"(price ${close:.2f} vs VWAP {vwap_str}). "
                    f"SPY macro or VWAP needs to align before entering CALL."
                )
            narrative = (
                f"🟡 [{ticker}] {bar_t} — ORB BREAK UP ↑ | "
                f"Price ${close:.2f} above OR HIGH ${or_high:.2f} (+${ext:.2f} extension) | "
                f"OR range: ${or_low:.2f}–${or_high:.2f} (${or_range} wide) | "
                f"{rvol_label} | {vwap_label} | {conclusion}"
            )

        elif close < or_low:
            ext     = round(or_low - close, 2)
            vwap_ok = vwap_below
            n_passed = sum([rvol_ok, vwap_ok])

            if n_passed == 2:
                conclusion = (
                    f"🔥 ALL 3 ORB GATES MET — evaluating PUT entry this bar. "
                    f"If filled: stop at OR HIGH ${or_high:.2f}, "
                    f"Stage 1 target ~${round(close * 0.99, 2):.2f} (1% below entry)."
                )
            elif not rvol_ok and not vwap_ok:
                conclusion = (
                    f"⏳ Price broke down but volume and VWAP both unconfirmed. "
                    f"Waiting for selling pressure and VWAP to confirm PUT direction. "
                    f"Need RVOL ≥{_ORB_RVOL:.1f}× AND price below VWAP {vwap_str}."
                )
            elif not rvol_ok:
                conclusion = (
                    f"⏳ Price below OR LOW but sellers not showing up in volume yet "
                    f"({rvol_val:.1f}×). Low-volume breakdowns trap shorts. "
                    f"Waiting for volume to confirm before PUT entry."
                )
            else:
                conclusion = (
                    f"⏳ Volume confirms selling but VWAP misaligned "
                    f"(price ${close:.2f} vs VWAP {vwap_str}). "
                    f"Need macro alignment before PUT entry."
                )
            narrative = (
                f"🟡 [{ticker}] {bar_t} — ORB BREAK DOWN ↓ | "
                f"Price ${close:.2f} below OR LOW ${or_low:.2f} (-${ext:.2f}) | "
                f"OR range: ${or_low:.2f}–${or_high:.2f} (${or_range} wide) | "
                f"{rvol_label} | {vwap_label} | {conclusion}"
            )

        else:
            # ── Inside the Opening Range ──────────────────────────────────────
            dist_hi = round(or_high - close, 2)
            dist_lo = round(close - or_low, 2)

            # Which breakout is closer?
            if dist_hi < dist_lo:
                prox = f"${dist_hi:.2f} below CALL trigger (${or_high:.2f})"
                bias_hint = "leaning CALL if it clears" if vwap_above else "CALL trigger close — VWAP alignment will matter"
            else:
                prox = f"${dist_lo:.2f} above PUT trigger (${or_low:.2f})"
                bias_hint = "leaning PUT if it breaks" if vwap_below else "PUT trigger close — VWAP alignment will matter"

            # VWAP Pullback awareness
            if vwap_val:
                _vwap_gap = round(abs(close - vwap_val), 2)
                if _vwap_gap < 0.30 and rvol_ok:
                    _vwap_pb_note = (
                        f" Price is ${_vwap_gap:.2f} from VWAP — "
                        f"if price bounces off VWAP with volume, that's also a VWAP Pullback setup."
                    )
                else:
                    _vwap_pb_note = ""
            else:
                _vwap_pb_note = ""

            if rvol_ok:
                vol_note = (
                    f"Volume is primed ({rvol_val:.1f}×) ✅ — "
                    f"just waiting for price to pick a side outside the range."
                )
            else:
                vol_note = (
                    f"Volume still light ({rvol_val:.1f}×) ❌ — "
                    f"need BOTH a range breakout AND volume before entering."
                )

            narrative = (
                f"🟡 [{ticker}] {bar_t} — INSIDE RANGE | "
                f"Price ${close:.2f} in OR ${or_low:.2f}–${or_high:.2f} (${or_range} wide) | "
                f"{prox} ({bias_hint}) | "
                f"{rvol_label} | {vwap_label} | "
                f"{vol_note}{_vwap_pb_note}"
            )

        log_event("INFO", "bar_eval", narrative)

    except Exception as _be:
        logger.debug("_log_bar_thinking error: %s", _be)


# ── Ghost-position reconciliation ────────────────────────────────────────────

def _check_ghost_positions(alpaca: "AlpacaClient") -> Optional[dict]:
    """
    Returns a dict describing any Alpaca position(s) not tracked in the DB,
    or None if Alpaca's positions agree with the DB (or the fetch failed).

    Two classes of "position in Alpaca but not in open DB":
      1. FAILED-CLOSE: bot marked it closed in DB but Alpaca sell never filled.
         Action → silently retry the close via alpaca.close_position().
      2. TRUE GHOST: no DB record at all.
         Action → auto-adopt into the journal; alert only if adoption fails.
    """
    global _ghost_alert_logged

    from database import log_event, get_open_trades, insert_trade, get_conn

    try:
        positions = alpaca.get_positions()
    except Exception:
        return None

    db_open    = get_open_trades()
    db_symbols = {t.get("contract_symbol") for t in db_open}
    ghosts     = [p for p in positions if p.get("symbol") not in db_symbols]

    if not ghosts:
        _ghost_alert_logged = False
        return None

    # ── Classify each ghost ───────────────────────────────────────────────────
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
    true_ghosts = [p for p in ghosts if p.get("symbol") not in failed_close_symbols]
    if not true_ghosts:
        _ghost_alert_logged = False
        return None

    still_unrecorded = []
    for p in true_ghosts:
        sym = p.get("symbol", "")
        # Parse OCC symbol: e.g. SPY260624C00754000
        _m = re.match(r'^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$', sym)
        if not _m:
            still_unrecorded.append(p)
            continue
        _tkr, _yy, _mo, _dy, _cp, _strike_raw = _m.groups()
        _expiry    = f"20{_yy}-{_mo}-{_dy}"
        _opt_type  = "call" if _cp == "C" else "put"
        _strike    = float(_strike_raw) / 1000.0
        try:
            _qty = int(p.get("qty") or 1)
            _cost = float(p.get("cost_basis") or 0)
            _entry_px = (_cost / _qty / 100) if _qty else 0.0
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


def _sweep_orphaned_orders(alpaca: "AlpacaClient", open_trades: list) -> None:
    """
    Cancel any resting Alpaca order whose symbol doesn't belong to a
    currently-tracked open trade.
    """
    from database import log_event

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
