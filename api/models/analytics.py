"""
api/models/analytics.py — Trade analytics breakdown schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from pydantic import BaseModel


class StrategyRow(BaseModel):
    strategy_id: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_win: float        # avg P&L on winning trades
    avg_loss: float       # avg P&L on losing trades (negative)
    profit_factor: float  # gross_wins / abs(gross_losses)
    avg_mfe_pct: float

class HourRow(BaseModel):
    hour: int
    label: str      # e.g. "9:30", "10:00"
    trades: int
    wins: int
    win_rate: float
    avg_pnl: float

class TickerRow(BaseModel):
    ticker: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float

class ExitReasonRow(BaseModel):
    reason: str
    trades: int
    total_pnl: float
    avg_pnl: float

class TradeAnalytics(BaseModel):
    by_strategy: list[StrategyRow]
    by_hour: list[HourRow]
    by_ticker: list[TickerRow]
    by_exit_reason: list[ExitReasonRow]
    avg_mfe_pct: float
    avg_exit_pct: float
    avg_exit_efficiency_pct: float
