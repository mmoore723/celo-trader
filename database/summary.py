"""
database/summary.py — Daily P&L rollup: _upsert_daily_summary (called
by close_trade and backfill_daily_summaries), get_daily_summaries (calendar
heatmap), get_cumulative_pnl (equity curve).

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging
from datetime import date

from database.connection import get_conn, _conn_for_mode

logger = logging.getLogger("celo_trader.database")

# ── Daily summary ─────────────────────────────────────────────────────────────

def _upsert_daily_summary(trade_date: date, pnl: float) -> None:
    """Increment (or insert) the daily summary row when a trade closes."""
    ds = trade_date.isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT total_pnl, num_trades, num_wins FROM daily_summary WHERE trade_date = ?",
            (ds,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE daily_summary
                SET total_pnl  = total_pnl  + ?,
                    num_trades = num_trades + 1,
                    num_wins   = num_wins   + ?
                WHERE trade_date = ?
                """,
                (pnl, 1 if pnl > 0 else 0, ds),
            )
        else:
            conn.execute(
                "INSERT INTO daily_summary VALUES (?, ?, 1, ?)",
                (ds, pnl, 1 if pnl > 0 else 0),
            )


def get_daily_summaries(mode: str = "paper") -> list[dict]:
    """
    Return daily P&L summary rows for the calendar heatmap.
    Opens the mode-specific DB directly so the Performance page's Paper/Live
    toggle always reads the right database.
    """
    try:
        with _conn_for_mode(mode) as conn:
            rows = conn.execute(
                """
                SELECT date(COALESCE(exit_time, entry_time)) AS trade_date,
                       SUM(COALESCE(realized_pnl, 0))        AS pnl,
                       COUNT(*)                              AS trades,
                       ROUND(
                         100.0 * SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END)
                         / NULLIF(COUNT(*), 0), 1
                       )                                     AS win_rate
                FROM trades
                WHERE status = 'closed'
                GROUP BY trade_date
                ORDER BY trade_date
                """,
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_daily_summaries(%s) failed: %s", mode, e)
        return []


def get_cumulative_pnl() -> list[dict]:
    """Return date + running cumulative P&L for the equity-curve chart."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT trade_date, total_pnl FROM daily_summary ORDER BY trade_date"
        ).fetchall()

    cumulative, result = 0.0, []
    for r in rows:
        cumulative += r["total_pnl"]
        result.append({"date": r["trade_date"], "cumulative_pnl": cumulative})
    return result


