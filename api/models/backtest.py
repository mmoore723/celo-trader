"""
api/models/backtest.py — Backtest request/result schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


class BacktestRequest(BaseModel):
    ticker: str
    months: int = 3
    start_date: Optional[str] = None   # YYYY-MM-DD; if provided with end_date, overrides months
    end_date: Optional[str] = None     # YYYY-MM-DD
    starting_capital: float = 1000.0
    direction: str = "both"            # "both" | "calls_only" | "puts_only"
    risk_pct: Optional[float] = None   # flat override e.g. 0.05 = 5%; None = live 4-tier ladder
    holdout_pct: Optional[float] = None  # e.g. .30: final 30% is locked evaluation


class BacktestResult(BaseModel):
    total_return_pct: float
    win_rate_pct: float
    total_trades: int
    avg_win: float
    avg_loss: float
    sharpe: float
    max_drawdown_pct: float
    final_balance: float
    stage1_rate_pct: float
    daily_pnl: dict[str, float]
    exit_reasons: dict[str, Any]
    trades: list[dict]
    # Call vs Put breakdown
    call_trades: int = 0
    put_trades: int = 0
    call_win_rate: float = 0.0
    put_win_rate: float = 0.0
    call_pnl: float = 0.0
    put_pnl: float = 0.0
    # Per-strategy breakdown: {strategy_id: {trades, wins, win_rate, pnl}}
    strategy_breakdown: dict[str, Any] = {}
    model_fidelity: dict[str, Any] = {}
    error: Optional[str] = None
    holdout: Optional[dict[str, Any]] = None


class BacktestJobStatus(BaseModel):
    job_id: str
    status: str
    result: Optional[BacktestResult] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_days: int = 0
    total_days: int = 0
    estimated_remaining_seconds: Optional[int] = None
