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
    Emit one human-readable 🟡 audit log entry per newly closed 1-min candle.

    df1m  — today's 1-min bars (drives narrative timing and current price/time)
    df5   — 5-min bars augmented with history (used for ORB range + RVOL/VWAP
            calculations, which need multi-day context to be meaningful)
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
