"""
signal_journal/queries.py — read-side helpers for the signal_journal table:
get_todays_rows(), get_todays_summary(), get_latest_per_ticker_today(),
get_trend().

Split out of the old single signal_journal.py (2026-08-01, file-size
cleanup); no logic changed, only relocated.
"""
from __future__ import annotations

from typing import Optional

from database import get_conn, _now_et


def get_todays_rows(
    ticker: Optional[str] = None,
    strategy: Optional[str] = None,
    reason: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Today's rows (ET calendar day), newest first, optionally filtered."""
    _today = _now_et().strftime("%Y-%m-%d")
    with get_conn() as conn:
        query = "SELECT * FROM signal_journal WHERE ts LIKE ?"
        params: list = [f"{_today}%"]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        if strategy:
            query += " AND strategy_id = ?"
            params.append(strategy)
        if reason:
            query += " AND reason_code = ?"
            params.append(reason)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_todays_summary() -> dict:
    """
    Today's breakdown: total signals, entered count, and a count per
    reason_code for every blocked signal — the data behind the panel's
    top summary bar (e.g. "82 signals, 3 entered, confidence floor 62").
    """
    _today = _now_et().strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT outcome, reason_code, COUNT(*) as n FROM signal_journal "
            "WHERE ts LIKE ? GROUP BY outcome, reason_code",
            (f"{_today}%",),
        ).fetchall()
    entered = 0
    by_reason: dict[str, int] = {}
    for r in rows:
        if r["outcome"] == "entered":
            entered += r["n"]
        else:
            by_reason[r["reason_code"] or "unknown"] = r["n"]
    total = entered + sum(by_reason.values())
    return {"total": total, "entered": entered, "by_reason": by_reason}


def get_latest_per_ticker_today() -> dict[str, dict]:
    """
    Today's single most recent journal row for every ticker that had at
    least one signal — the "Blocked" status source for the ticker board
    (api/routes/tickers.py). One row per ticker, not the full day's list,
    since the board only needs "what's true right now" per ticker.
    """
    _today = _now_et().strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT sj.* FROM signal_journal sj
               INNER JOIN (
                   SELECT ticker, MAX(id) as max_id FROM signal_journal
                   WHERE ts LIKE ? GROUP BY ticker
               ) latest ON sj.ticker = latest.ticker AND sj.id = latest.max_id""",
            (f"{_today}%",),
        ).fetchall()
        return {r["ticker"]: dict(r) for r in rows}


def get_trend(reason_code: str, days: int = 7) -> list[dict]:
    """
    Daily count of one reason_code over the last *days* calendar days —
    the small bar strip that answers "is this gate a today problem or a
    systemic one" without loading a full week of individual rows.
    """
    # Cutoff computed in ET (Python side) rather than SQLite's date('now'),
    # which is UTC — ts is stored as ET isoformat, so a UTC cutoff would
    # misalign by hours right around midnight ET.
    from datetime import timedelta
    _cutoff = (_now_et() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT substr(ts, 1, 10) as day, COUNT(*) as n FROM signal_journal "
            "WHERE reason_code = ? AND outcome = 'blocked' AND ts >= ? "
            "GROUP BY day ORDER BY day ASC",
            (reason_code, _cutoff),
        ).fetchall()
        return [{"date": r["day"], "count": r["n"]} for r in rows]
