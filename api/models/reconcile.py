"""
api/models/reconcile.py — Broker-vs-bot reconciliation schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class AlpacaOrder(BaseModel):
    order_id: str
    symbol: str
    side: str                       # "buy" | "sell"
    qty: int
    filled_qty: int
    filled_avg_price: Optional[float]
    status: str
    submitted_at: Optional[str]
    filled_at: Optional[str]

class ReconcileRow(BaseModel):
    # DB trade info
    trade_id: Optional[int]
    ticker: Optional[str]
    strategy_id: Optional[str]
    contracts: Optional[int]
    contract_symbol: Optional[str]
    status: Optional[str] = None    # "open" | "closed" — 2026-07-28: open positions are now
                                     # included here (matched on entry only) instead of only
                                     # ever appearing as an "unmatched" Alpaca fill
    # Bot-recorded prices
    bot_entry: Optional[float]
    bot_exit: Optional[float]
    bot_pnl: Optional[float]
    entry_time: Optional[str]
    exit_time: Optional[str]
    # Alpaca actual prices
    alpaca_entry: Optional[float]
    alpaca_exit: Optional[float]
    alpaca_pnl: Optional[float]     # computed: (alpaca_exit - alpaca_entry) * contracts * 100
    # Gap
    pnl_gap: Optional[float]        # bot_pnl - alpaca_pnl
    has_gap: bool                   # True if |gap| > $1

class ReconcileResponse(BaseModel):
    date: str
    broker_provider: str = "alpaca"
    alpaca_equity: Optional[float]          # current Alpaca account equity
    day_start_balance: Optional[float]      # captured at bot start
    bot_session_pnl: float                  # sum of DB realized_pnl for the date
    alpaca_session_pnl: Optional[float]     # equity - day_start
    equity_gap: Optional[float]             # bot_session_pnl - alpaca_session_pnl
    trades: list[ReconcileRow]
    unmatched_alpaca_orders: list[AlpacaOrder]  # Alpaca orders with no DB match
