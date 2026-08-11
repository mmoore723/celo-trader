"""
api/models/performance.py — Daily/overall performance summary schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from pydantic import BaseModel


class DailySummary(BaseModel):
    date: str
    pnl: float
    trades: int
    win_rate: float


class PerformanceStats(BaseModel):
    total_pnl: float
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    best_day: float
    worst_day: float
    current_streak: int
    daily_summaries: list[DailySummary]
    account_scoped: bool
    data_scope_note: str
