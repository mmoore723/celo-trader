"""
trading/diagnostics/ghost_positions.py — _check_ghost_positions: detects both
directions of broker/journal drift: Alpaca positions missing from the local DB
and journal-open contracts that Alpaca no longer holds.

Split out of the old single trading/diagnostics.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from trading.state import get_user_state, get_user_risk, _now_et, _default_user_id

logger = logging.getLogger("celo_trader.trading_logic")

# FIX: was a single module-level bool, shared by every user's thread — one
# user's ghost-position alert being acknowledged would silently suppress a
# DIFFERENT user's still-unresolved ghost alert. Now keyed per user.
_ghost_alert_logged: dict[str, bool] = {}
_phantom_alert_logged: dict[str, set[str]] = {}
_alignment_detected_at: dict[str, str] = {}


def _find_db_only_positions(
    db_open: list[dict],
    broker_positions: list[dict],
    open_orders: list[dict],
    *,
    now: datetime,
    grace_seconds: int = 120,
) -> list[dict]:
    """Find journal-open contracts that Alpaca no longer holds.

    A newly-created trade may briefly precede Alpaca's positions endpoint and
    a working exit order may legitimately remove the position between polls.
    The grace window and working-order exclusion prevent those normal races
    from becoming false alarms.
    """
    held = {str(p.get("symbol") or "") for p in broker_positions}
    working = {str(o.get("symbol") or "") for o in open_orders}
    issues: list[dict] = []
    for trade in db_open:
        symbol = str(trade.get("contract_symbol") or "")
        if not symbol or symbol in held or symbol in working:
            continue
        try:
            entered = datetime.fromisoformat(str(trade.get("entry_time") or ""))
            if entered.tzinfo is None:
                entered = entered.replace(tzinfo=now.tzinfo)
            age_seconds = max(0, int((now - entered).total_seconds()))
        except Exception:
            age_seconds = grace_seconds + 1
        if age_seconds <= grace_seconds:
            continue
        issues.append({
            "kind": "journal_open_broker_flat",
            "trade_id": trade.get("id"),
            "symbol": symbol,
            "ticker": trade.get("ticker"),
            "age_seconds": age_seconds,
            "message": (
                f"Trade #{trade.get('id')} is open in the journal, but Alpaca "
                f"has no {symbol} position or working order."
            ),
        })
    return issues

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
    _uid = _default_user_id()

    from database import log_event, get_open_trades, insert_trade, get_conn
    from config import get_settings

    _account_id = get_settings().get("active_broker_account_id") or None

    try:
        from broker.recovery import reconcile_orders
        pending_symbols = reconcile_orders(alpaca)
        positions = alpaca.get_positions()
    except Exception as exc:
        logger.warning("position_recovery_snapshot_unavailable: %s", exc)
        return {"detected_at": _now_et().isoformat(), "positions": [], "issues": [{
            "kind": "recovery_unavailable", "message": "Broker reconciliation unavailable; no positions were inferred or changed.",
        }]}

    db_open    = get_open_trades(broker_account_id=_account_id)
    db_symbols = {t.get("contract_symbol") for t in db_open}
    ghosts     = [p for p in positions if p.get("symbol") not in db_symbols | pending_symbols]
    try:
        open_orders: list[dict] | None = alpaca.get_open_orders()
    except Exception as exc:
        logger.warning("position_alignment_open_orders_failed: %s", exc)
        open_orders = None
    # Do not infer broker-flat while the working-order snapshot is unavailable.
    # An in-flight entry/exit could otherwise become a false reconciliation alarm.
    phantom_issues = (
        _find_db_only_positions(db_open, positions,
                               open_orders + [{"symbol": s} for s in pending_symbols], now=_now_et())
        if open_orders is not None
        else []
    )
    phantom_issues.extend({"kind": "order_recovery_pending", "symbol": symbol,
                          "message": f"{symbol}: checking unresolved broker order; confirmed fills remain tracked."}
                         for symbol in pending_symbols)
    current_phantoms = {str(issue["symbol"]) for issue in phantom_issues}
    previous_phantoms = _phantom_alert_logged.get(_uid, set())
    for issue in phantom_issues:
        if issue["symbol"] not in previous_phantoms:
            log_event("CRITICAL", "reconciliation", f"🚨 {issue['message']}")
            logger.critical("journal_open_broker_flat", extra={"event": "journal_open_broker_flat", **issue})
    _phantom_alert_logged[_uid] = current_phantoms

    if not ghosts and not phantom_issues:
        _ghost_alert_logged[_uid] = False
        _alignment_detected_at.pop(_uid, None)
        return None

    # ── Classify each ghost ───────────────────────────────────────────────────
    ghost_symbols = {p.get("symbol") for p in ghosts}
    try:
        with get_conn() as _gc:
            _today_str = _now_et().strftime("%Y-%m-%d")
            _closed_today = _gc.execute(
                """SELECT contract_symbol FROM trades
                   WHERE status='closed'
                   AND date(exit_time) = ?
                   AND (? IS NULL OR broker_account_id = ?)""",
                (_today_str, _account_id, _account_id),
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
    if not true_ghosts and not phantom_issues:
        _ghost_alert_logged[_uid] = False
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
                paper           = bool(get_settings().get("paper_trading", True)),
                broker_account_id = _account_id,
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

    if not still_unrecorded and not phantom_issues:
        _ghost_alert_logged[_uid] = False
        return None

    if not _ghost_alert_logged.get(_uid, False):
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
        _ghost_alert_logged[_uid] = True

    return {
        "detected_at": _alignment_detected_at.setdefault(_uid, _now_et().isoformat()),
        "issues": phantom_issues,
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
