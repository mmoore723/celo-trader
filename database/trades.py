"""
database/trades.py — Trade writes: insert_trade (entry), save_mtf_bias
(best-effort MTF-alignment follow-up), close_trade (exit, incl. daily_summary
upsert and annotations-JSON merge).

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging
from datetime import date, datetime
from typing import Optional

from database.connection import get_conn
from database.helpers import _to_et_isoformat, _merge_annotations_json
from database.summary import _upsert_daily_summary

logger = logging.getLogger("celo_trader.database")


def audit_trade_lineage(trade_id: int) -> list[str]:
    """Return missing durable links for one trade without changing it."""
    missing: list[str] = []
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            return ["trade"]
        trade = dict(row)
        recovered = trade.get("strategy_id") == "RECOVERED_UNTRACKED"
        if not trade.get("candidate_id") and not recovered:
            missing.append("candidate_id")
        elif trade.get("candidate_id"):
            candidate = conn.execute(
                "SELECT linked_trade_id FROM shadow_candidates WHERE candidate_id = ?",
                (trade["candidate_id"],),
            ).fetchone()
            if candidate is None or candidate["linked_trade_id"] != trade_id:
                missing.append("candidate_link")
        journal = conn.execute(
            "SELECT id FROM signal_journal WHERE trade_id = ? AND outcome = 'entered' LIMIT 1",
            (trade_id,),
        ).fetchone()
        if journal is None and not recovered:
            missing.append("signal_journal")
        if not trade.get("entry_order_id") and not recovered:
            missing.append("entry_order_id")
        if not trade.get("entry_fill_time") and not recovered:
            missing.append("entry_fill_time")
        if trade.get("status") == "closed":
            if not trade.get("exit_order_id"):
                missing.append("exit_order_id")
            if not trade.get("exit_fill_time"):
                missing.append("exit_fill_time")
            if trade.get("peak_price") is None:
                missing.append("mfe")
            if trade.get("mae_price") is None:
                missing.append("mae")
    return missing

def insert_trade(
    ticker: str,
    contract_symbol: str,
    option_type: str,
    strike: float,
    expiry: str,
    contracts: int,
    entry_price: float,
    entry_time: datetime,
    entry_reason: str,
    paper: bool = True,
    strategy_id: str = "UNKNOWN",   # which reviewed strategy generated this signal
    stop_price: Optional[float] = None,    # option premium stop-loss level at entry
    target_price: Optional[float] = None,  # Stage-1 target at entry
    annotations_json: Optional[str] = None,  # JSON snapshot of entry-time chart annotations
    tier: str = "main",                       # main setup pool | separately measured opportunity pool
    broker_account_id: Optional[str] = None,   # active Alpaca account/mode identity at entry
    candidate_id: Optional[str] = None,
    parent_trade_id: Optional[int] = None,
    entry_order_id: Optional[str] = None,
    entry_fill_time: Optional[datetime | str] = None,
) -> int:
    """
    Insert an open trade.  Returns the new row id so we can update it on close.
    All timestamps stored as US/Eastern ISO strings for session-time alignment.
    """
    sql = """
        INSERT INTO trades
            (ticker, contract_symbol, option_type, strike, expiry,
             contracts, entry_price, entry_time, entry_reason,
             status, paper, strategy_id, stop_price, target_price, annotations_json,
             tier, broker_account_id, candidate_id, parent_trade_id,
             entry_order_id, entry_fill_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_conn() as conn:
        cur = conn.execute(sql, (
            ticker, contract_symbol, option_type, strike, expiry,
            contracts, entry_price, _to_et_isoformat(entry_time), entry_reason,
            1 if paper else 0, strategy_id, stop_price, target_price, annotations_json,
            tier if tier in ("main", "opportunity") else "main", broker_account_id,
            candidate_id, parent_trade_id, entry_order_id,
            _to_et_isoformat(entry_fill_time) if entry_fill_time is not None else None,
        ))
        trade_id = cur.lastrowid
    logger.info(
        "Trade %d opened: %s %s @ %.2f [strategy=%s tier=%s]",
        trade_id, ticker, contract_symbol, entry_price, strategy_id, tier,
    )
    return trade_id


def save_mtf_bias(trade_id: int, mtf_bias_json: Optional[str]) -> None:
    """
    Save the multi-timeframe alignment snapshot computed by
    trading/mtf_features.py::compute_mtf_alignment() onto an already-recorded
    trade. Deliberately a separate, tiny UPDATE rather than a param on
    insert_trade() — the MTF fetch needs 3 extra API calls, and the trade
    itself must be recorded FIRST regardless of whether that lookup
    succeeds. Called by trading/entry.py only after insert_trade() has
    already returned successfully.

    Never raises: a failed save here must not affect a trade that already
    exists in the database. Logs a warning and returns on any error.
    """
    if not mtf_bias_json:
        return
    try:
        with get_conn() as conn:
            conn.execute("UPDATE trades SET mtf_bias_json = ? WHERE id = ?", (mtf_bias_json, trade_id))
    except Exception:
        logger.warning("save_mtf_bias failed for trade %d — trade itself is unaffected", trade_id, exc_info=True)


def close_trade(
    trade_id: int,
    exit_price: float,
    exit_time: datetime,
    exit_reason: str,
    confirmed_fill_price: Optional[float] = None,
    peak_price: Optional[float] = None,   # MFE: highest option mid-price seen during trade
    mae_price: Optional[float] = None,    # MAE: lowest  option mid-price seen during trade
    paper: bool = True,                   # False → deduct Alpaca commission from P&L
    recap: Optional[str] = None,          # Auto-generated trade recap stored in DB
    annotations_json: Optional[str] = None,  # JSON snapshot of exit-time chart annotations
    exit_order_id: Optional[str] = None,
    exit_fill_time: Optional[datetime | str] = None,
) -> float:
    """
    Mark a trade closed and compute realised P&L.
    FIX N2: If confirmed_fill_price is provided (from broker fill confirmation),
    use that for P&L calculation instead of intended exit_price.
    peak_price / mae_price are the MFE and MAE values tracked live by position_manager.
    Commission ($0.65/contract × 2 legs) is deducted for live trades only.
    Returns the realised P&L in dollars (net of commissions on live).
    """
    from config import COMMISSION_PER_CONTRACT
    actual_exit = confirmed_fill_price if confirmed_fill_price else exit_price

    with get_conn() as conn:
        row = conn.execute(
            "SELECT entry_price, contracts, annotations_json, contract_symbol FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Trade id {trade_id} not found in database")

        entry_price  = row["entry_price"]
        contracts    = row["contracts"]
        realized_pnl = (actual_exit - entry_price) * contracts * 100

        # Manual, panic, and reconciliation closes do not always have a
        # position-manager price sample.  Store a neutral entry-price value
        # rather than NULL so every new closed trade has a complete outcome
        # row.  This denotes no observed intratrade excursion, not proof that
        # the option price never moved.
        if peak_price is None:
            peak_price = entry_price
        if mae_price is None:
            mae_price = entry_price

        # Deduct round-trip commission on live trades (entry leg + exit leg).
        # Paper trading has no commissions — Alpaca paper is fee-free.
        if not paper:
            commission   = contracts * COMMISSION_PER_CONTRACT * 2
            realized_pnl = realized_pnl - commission
            logger.debug("Commission deducted: contracts=%d commission=$%.2f", contracts, commission)

        # Merge exit-time annotations with whatever was already saved at entry
        # (rather than overwrite) so the trade keeps its FULL story — why it
        # opened AND why it closed. See _merge_annotations_json above.
        merged_annotations = _merge_annotations_json(row["annotations_json"], annotations_json)

        conn.execute(
            """
            UPDATE trades
            SET exit_price = ?, exit_time = ?, exit_reason = ?,
                realized_pnl = ?, status = 'closed',
                peak_price = ?, mae_price = ?, recap = ?, annotations_json = ?,
                exit_order_id = ?, exit_fill_time = ?
            WHERE id = ?
            """,
            (actual_exit, _to_et_isoformat(exit_time), exit_reason,
             realized_pnl, peak_price, mae_price, recap, merged_annotations,
             exit_order_id,
             _to_et_isoformat(exit_fill_time) if exit_fill_time is not None else None,
             trade_id),
        )

    logger.info(
        "Trade %d closed: exit=%.4f (confirmed=%.4f) reason=%s pnl=$%.2f",
        trade_id, exit_price, actual_exit, exit_reason, realized_pnl,
    )

    # Every confirmed PAPER close receives a durable exit observation.  The
    # position manager records richer bid/mid evidence first when available;
    # the unique minute key makes this a safe fallback for manual, panic, and
    # reconciliation closes that otherwise have no quote row at all.
    if paper:
        try:
            from database.option_quotes import record_paper_option_quote
            record_paper_option_quote(
                trade_id=trade_id,
                contract_symbol=row["contract_symbol"],
                observation_kind="exit",
                observed_at=exit_time,
                quote={"mid": exit_price},
                source="trade_close",
                fill_price=actual_exit,
            )
        except Exception:
            logger.warning("paper close quote capture failed for trade %s", trade_id, exc_info=True)

    # Update daily summary — wrapped so a transient DB error never blocks the close
    try:
        _upsert_daily_summary(exit_time.date(), realized_pnl)
    except Exception as _e:
        logger.warning("_upsert_daily_summary failed (non-fatal): %s — will backfill on next startup", _e)

    # Reflect P&L in last_known_balance so the dashboard shows the correct balance
    # even when the bot is in STANDBY (not actively fetching Alpaca account equity).
    # The broker-fetch path in trading_logic._tick() will override this with the
    # authoritative Alpaca value the next time the bot runs.
    try:
        from config import get_settings as _gs, save_settings as _ss
        _cur_bal = float(_gs().get("last_known_balance") or 0.0)
        _ss({"last_known_balance": round(_cur_bal + realized_pnl, 2)})
    except Exception as _e:
        logger.warning("Could not update last_known_balance after trade close: %s", _e)

    return realized_pnl
