"""
risk/db_helpers.py — Persistent state reads/writes used by the risk engine.

Split out of risk.py (2026-08-01, file-size cleanup) — pure DB functions,
no RiskManager state.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from database import get_conn

logger   = logging.getLogger("celo_trader.risk")
db_mutex = threading.Lock()  # Thread lock prevents SQLite concurrent write crashes


def get_todays_realized_pnl() -> float:
    """
    Read today's realized P&L directly from the database with an operational thread lock.
    """
    # CRITICAL FIX 2026-07-15: removed "AND paper = 0". The DB file is already
    # mode-separated (trades_paper.db vs trades_live.db), so in paper mode every
    # (Confirmed 2026-07-15: -34% single-day loss with no halt.)
    from config import get_settings
    start = datetime.now(ZoneInfo("America/New_York")).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    account_id = get_settings().get("active_broker_account_id")
    if not account_id:
        raise RuntimeError("Account identity required to verify today's realized P&L")
    scope = " AND broker_account_id = ?" if account_id else ""
    params = [start.isoformat(), end.isoformat()]
    if account_id:
        params.append(account_id)
    try:
        with db_mutex:
            with get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(realized_pnl), 0.0)
                    FROM trades
                    WHERE status = 'closed'
                      AND julianday(exit_time) >= julianday(?)
                      AND julianday(exit_time) < julianday(?)
                    """ + scope,
                    params,
                ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error("get_todays_realized_pnl failed: %s", e)
        raise RuntimeError("Cannot verify today's realized P&L; entries blocked") from e


def persist_peak_price(trade_id: int, peak_price: float) -> None:
    """
    Write peak price to the system_events table so it survives unexpected restarts.
    """
    try:
        with db_mutex:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO system_events (ts, level, component, message)
                    VALUES (?, 'INFO', 'peak_price', ?)
                    """,
                    (datetime.utcnow().isoformat(), f"trade_id={trade_id} peak={peak_price:.4f}"),
                )
    except Exception as e:
        logger.warning("persist_peak_price failed (non-critical): %s", e)


def recover_peak_price(trade_id: int) -> Optional[float]:
    """
    Recover peak price from DB after a workspace crash or engine restart.
    """
    try:
        with db_mutex:
            with get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT message FROM system_events
                    WHERE component = 'peak_price'
                      AND message LIKE ?
                    ORDER BY ts DESC LIMIT 1
                    """,
                    (f"trade_id={trade_id}%",),
                ).fetchone()
        if row:
            parts = dict(kv.split("=") for kv in row[0].split())
            return float(parts.get("peak", 0))
    except Exception:
        pass
    return None
