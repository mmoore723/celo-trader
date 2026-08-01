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
    strategy_id: str = "INST_ORB",   # which router strategy generated this signal
    stop_price: Optional[float] = None,    # option premium stop-loss level at entry
    target_price: Optional[float] = None,  # Stage-1 target at entry
    annotations_json: Optional[str] = None,  # JSON snapshot of entry-time chart annotations
) -> int:
    """
    Insert an open trade.  Returns the new row id so we can update it on close.
    All timestamps stored as US/Eastern ISO strings for session-time alignment.
    """
    sql = """
        INSERT INTO trades
            (ticker, contract_symbol, option_type, strike, expiry,
             contracts, entry_price, entry_time, entry_reason,
             status, paper, strategy_id, stop_price, target_price, annotations_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)
    """
    with get_conn() as conn:
        cur = conn.execute(sql, (
            ticker, contract_symbol, option_type, strike, expiry,
            contracts, entry_price, _to_et_isoformat(entry_time), entry_reason,
            1 if paper else 0, strategy_id, stop_price, target_price, annotations_json,
        ))
        trade_id = cur.lastrowid
    logger.info(
        "Trade %d opened: %s %s @ %.2f [strategy=%s]",
        trade_id, ticker, contract_symbol, entry_price, strategy_id,
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
            "SELECT entry_price, contracts, annotations_json FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Trade id {trade_id} not found in database")

        entry_price  = row["entry_price"]
        contracts    = row["contracts"]
        realized_pnl = (actual_exit - entry_price) * contracts * 100

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
                peak_price = ?, mae_price = ?, recap = ?, annotations_json = ?
            WHERE id = ?
            """,
            (actual_exit, _to_et_isoformat(exit_time), exit_reason,
             realized_pnl, peak_price, mae_price, recap, merged_annotations, trade_id),
        )

    logger.info(
        "Trade %d closed: exit=%.4f (confirmed=%.4f) reason=%s pnl=$%.2f",
        trade_id, exit_price, actual_exit, exit_reason, realized_pnl,
    )

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


