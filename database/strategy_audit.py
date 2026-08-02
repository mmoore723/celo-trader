"""
database/strategy_audit.py — strategy_audits table access: save/read the
periodic (daily/weekly) per-strategy funnel audits used by strategy_health/.

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from datetime import date
from typing import Optional

from database.connection import get_conn
from database.helpers import _now_et

# ── Strategy health audits (strategy_health/ package) ─────────────────────────
# Replaces the one-off diag_*.py / ab_test_*.py scripts with a permanent,
# DB-backed daily audit: raw signals vs what survived the router, vs what
# actually traded. One row per calendar day audited.

def save_strategy_audit(row: dict) -> None:
    """
    row keys: audit_date, tickers, aggregate (dict), rule_summary, ai_summary,
    audit_type ('daily' | 'weekly', defaults 'daily' for backward compat).
    Uses INSERT OR REPLACE keyed on (audit_date, audit_type) so re-running
    the same period's audit (e.g. manual on-demand re-run) overwrites rather
    than duplicates — and so a weekly row for the same date string a daily
    row uses (e.g. a Friday) never collides with or deletes the daily row.
    """
    import json as _json
    audit_type = row.get("audit_type", "daily")
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM strategy_audits WHERE audit_date = ? AND audit_type = ?",
            (row["audit_date"], audit_type),
        )
        conn.execute(
            "INSERT INTO strategy_audits "
            "(audit_date, audit_type, created_at, tickers, aggregate_json, rule_summary, ai_summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["audit_date"],
                audit_type,
                _now_et().isoformat(),
                row.get("tickers", ""),
                _json.dumps(row["aggregate"], default=str),
                row.get("rule_summary"),
                row.get("ai_summary"),
            ),
        )


def get_latest_strategy_audit(audit_type: str = "daily") -> Optional[dict]:
    """Most recent audit row of the given type, with aggregate_json decoded
    back to a dict. audit_type defaults to 'daily' to preserve existing
    callers' behavior; pass 'weekly' for the Friday rollup.

    FIX 2026-07-17: this used to ORDER BY audit_date DESC, but audit_date can
    be the literal string "unknown" (runner.py falls back to it when no
    ticker produced a valid trading day that run — e.g. a data-fetch hiccup).
    "unknown" sorts AFTER any real "YYYY-MM-DD" string alphabetically, so one
    bad/empty run would permanently outrank every real dated audit forever,
    even ones that ran much later — exactly what caused the Strategy Health
    page to show "Audit for unknown — 0 tickers" while a real audit for that
    same day sat one row below it in history. created_at is always a real,
    reliably-sortable ISO timestamp regardless of what audit_date holds.
    """
    import json as _json
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_audits WHERE audit_type = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (audit_type,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["aggregate"] = _json.loads(result.pop("aggregate_json"))
    except Exception:
        result["aggregate"] = {}
    return result


def get_strategy_audit_history(limit: int = 30, audit_type: str = "daily") -> list[dict]:
    """Recent audits of the given type, newest first, WITHOUT the full
    aggregate JSON (keeps the history list endpoint light — callers fetch
    the latest for detail)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT audit_date, audit_type, created_at, tickers, rule_summary, ai_summary "
            "FROM strategy_audits WHERE audit_type = ? ORDER BY created_at DESC LIMIT ?",
            (audit_type, limit),
        ).fetchall()
    return [dict(r) for r in rows]
