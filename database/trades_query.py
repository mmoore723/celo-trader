"""
database/trades_query.py — Trade reads: get_open_trades, get_open_trade,
get_all_trades (mode-aware, for the Journal page).

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging
from typing import Optional

from database.connection import get_conn, _conn_for_mode

logger = logging.getLogger("celo_trader.database")


def _effective_account_id(
    broker_account_id: str | None,
    user_id: str | None = None,
) -> str | None:
    """Use the active account unless a caller deliberately supplies one.

    Legacy rows have no account identity. Once an account has been connected,
    treating those rows as the current account is misleading, so normal reads
    hide them. Startup/migration code can still explicitly request an account
    when it needs to reconcile broker state.
    """
    if broker_account_id is not None:
        return broker_account_id or None
    try:
        from config import get_settings
        return get_settings(user_id=user_id).get("active_broker_account_id") or None
    except Exception:
        return None


def get_open_trades(broker_account_id: str | None = None) -> list[dict]:
    """
    Return ALL currently-open trades (newest first), supporting up to
    MAX_CONCURRENT_POSITIONS simultaneous positions.

    If more than MAX_CONCURRENT_POSITIONS BOT-MANAGED trades are open (should
    never happen — the entry gate in trading_logic._tick() checks this count
    before placing a new order), log a CRITICAL alert since that indicates a
    bug or a manually-placed order, but still return every row so the caller
    can manage (and exit) all of them.

    FIX 2026-06-15: rows with strategy_id == "RECOVERED_UNTRACKED" (the 7
    legacy positions recovered from the ghost-position reconciliation) are
    EXCLUDED from this count. They're real open positions and are still
    returned in the list (so the Trade Journal's "Close Position" buttons and
    trading_logic._tick()'s own RECOVERED_UNTRACKED filter can see them), but
    they were never opened by this bot's MAX_CONCURRENT_POSITIONS-gated entry
    logic, so they shouldn't trip a "DATA INTEGRITY" alert or be counted
    against the 2-position cap.
    """
    from config import MAX_CONCURRENT_POSITIONS
    broker_account_id = _effective_account_id(broker_account_id)
    with get_conn() as conn:
        if broker_account_id:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' AND broker_account_id = ? "
                "ORDER BY entry_time DESC", (broker_account_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC"
            ).fetchall()
    _bot_managed = [r for r in rows if r["strategy_id"] != "RECOVERED_UNTRACKED"]
    if len(_bot_managed) > MAX_CONCURRENT_POSITIONS:
        logger.error(
            "DATA INTEGRITY: %d open trades found (expected max %d). Trade IDs: %s.",
            len(_bot_managed), MAX_CONCURRENT_POSITIONS, [r["id"] for r in _bot_managed],
        )
        log_event("CRITICAL", "database",
                  f"More open trades ({len(_bot_managed)}) than the {MAX_CONCURRENT_POSITIONS}-position "
                  f"limit allows: {[r['id'] for r in _bot_managed]}")
    return [dict(r) for r in rows]


def get_open_trade(broker_account_id: str | None = None) -> Optional[dict]:
    """
    Backward-compat helper — returns the single MOST RECENT open trade, or
    None. Used by manual-close / panic-close paths that only ever act on
    one position at a time. Multi-position management should use
    get_open_trades() instead.
    """
    trades = get_open_trades(broker_account_id=broker_account_id)
    return trades[0] if trades else None


def get_all_trades(
    limit: int = 500, mode: str = "paper", status_filter: str = "all",
    broker_account_id: str | None = None, user_id: str | None = None,
) -> list[dict]:
    """
    Return trades for the journal page.

    mode          — "paper" or "live". Opens the corresponding DB file directly
                    via _conn_for_mode() so the Journal's mode toggle always reads
                    the right database, regardless of which mode the bot is running.
    status_filter — "all" | "open" | "closed". Defaults to all.
    limit         — max rows returned.
    broker_account_id — when supplied, return only rows written for that
                         Alpaca account/mode identity.
    user_id           — when supplied, resolve the database for that user even
                         when the caller is outside its request ContextVar.
    """
    broker_account_id = _effective_account_id(broker_account_id, user_id=user_id)
    clauses: list[str] = []
    params: list[object] = []
    if status_filter in {"open", "closed"}:
        clauses.append("status = ?")
        params.append(status_filter)
    if broker_account_id:
        clauses.append("broker_account_id = ?")
        params.append(broker_account_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    ordering = "entry_time DESC" if status_filter == "open" else "COALESCE(exit_time, entry_time) DESC"
    sql = f"SELECT * FROM trades{where} ORDER BY {ordering} LIMIT ?"
    params.append(limit)

    try:
        with _conn_for_mode(mode, user_id=user_id) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_all_trades(%s) failed: %s", mode, e)
        return []
