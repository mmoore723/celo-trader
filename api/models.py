"""
api/models.py — Pydantic response schemas for all FastAPI endpoints.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


# ── Bot / Status ──────────────────────────────────────────────────────────────

class BotStatus(BaseModel):
    running: bool
    mode: str                        # "live" | "sim" | "stopped"
    ticker: Optional[str]
    account_balance: float
    session_pnl: float
    options_buying_power: float
    last_update: Optional[str]
    network_ok: bool
    last_strategy_id: Optional[str]
    current_stop_pct: Optional[float]
    last_signal: Optional[str]
    ghost_position_detected: bool
    is_paper: bool = True            # True = paper-trading, False = live account
    # ── Contract eval snapshot (written by entry.py after each signal eval) ────
    last_eval_strike: Optional[float] = None
    last_eval_expiry: Optional[str]   = None
    last_eval_contract_symbol: Optional[str] = None
    last_eval_eff_entry: Optional[float] = None


class BotActionResponse(BaseModel):
    ok: bool
    message: str


# ── Trades ────────────────────────────────────────────────────────────────────

class Trade(BaseModel):
    id: int
    ticker: str
    direction: str           # "long" | "short" — derived from option_type
    option_type: Optional[str]
    strategy_id: Optional[str]
    # ── Contract details ──────────────────────────────────────────────────────
    contract_symbol: Optional[str]
    strike: Optional[float]
    expiry: Optional[str]
    # ── Prices ────────────────────────────────────────────────────────────────
    entry_price: float
    exit_price: Optional[float]
    stop_price: Optional[float]   # option premium stop-loss level at entry
    target_price: Optional[float] # Stage-1 target at entry
    # ── Size / P&L ────────────────────────────────────────────────────────────
    contracts: int
    pnl: Optional[float]          # realized_pnl from DB
    status: str
    entry_time: Optional[str]
    exit_time: Optional[str]
    exit_reason: Optional[str]
    stage1_done: Optional[bool]
    mode: Optional[str]           # "paper" | "live" — derived from paper int column


class TradeListResponse(BaseModel):
    trades: list[Trade]
    total: int
    total_pnl: float
    win_rate: float


# ── Market data ───────────────────────────────────────────────────────────────

class Bar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float]
    vwap_upper1: Optional[float]
    vwap_lower1: Optional[float]
    vwap_upper2: Optional[float]
    vwap_lower2: Optional[float]
    rvol: Optional[float]
    atr: Optional[float]


class Quote(BaseModel):
    ticker: str
    price: float
    change_pct: float
    volume: float


class ScannerResult(BaseModel):
    ticker: str
    rvol: float
    price: float
    atr: float
    change_pct: float
    rank: int


# ── Settings ──────────────────────────────────────────────────────────────────

class Settings(BaseModel):
    risk_pct: float
    growth_mode: bool
    flip_trading_enabled: bool
    max_concurrent_positions: int
    rr_ratio_mode: str
    watchlist: list[str]
    orb_enabled: bool
    vwap_pullback_enabled: bool
    fvg_enabled: bool
    bos_mss_enabled: bool
    chan_break_enabled: bool = True
    mid_brk_enabled: bool = True
    trend_cont_enabled: bool = True


# ── Backtest ──────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    ticker: str
    months: int = 3
    starting_capital: float = 1000.0
    direction: str = "both"   # "both" | "calls_only" | "puts_only"


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
    error: Optional[str] = None


# ── Performance ───────────────────────────────────────────────────────────────

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
