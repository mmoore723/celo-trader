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
    # ── MFE / MAE ─────────────────────────────────────────────────────────────
    peak_price: Optional[float] = None   # highest option mid-price seen (MFE raw)
    mae_price: Optional[float] = None    # lowest  option mid-price seen (MAE raw)
    mfe_pct: Optional[float] = None      # (peak - entry) / entry * 100
    mae_pct: Optional[float] = None      # (mae  - entry) / entry * 100  (negative = adverse)
    exit_efficiency_pct: Optional[float] = None  # (exit - entry) / (peak - entry) * 100
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


# ── Analytics ─────────────────────────────────────────────────────────────────

class StrategyRow(BaseModel):
    strategy_id: str
    trades: int
    wins: int
    win_rate: float
    total_pnl: float
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
    win_rate: float
    total_pnl: float

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


# ── Options chain ──────────────────────────────────────────────────────────────

class OptionsChainRow(BaseModel):
    strike: float
    call_bid: Optional[float] = None
    call_ask: Optional[float] = None
    call_mid: Optional[float] = None
    call_delta: Optional[float] = None
    call_iv: Optional[float] = None
    call_oi: Optional[int] = None
    put_bid: Optional[float] = None
    put_ask: Optional[float] = None
    put_mid: Optional[float] = None
    put_delta: Optional[float] = None
    put_iv: Optional[float] = None
    put_oi: Optional[int] = None


# ── Backtest ──────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    ticker: str
    months: int = 3
    start_date: Optional[str] = None  # YYYY-MM-DD; if provided with end_date, overrides months
    end_date: Optional[str] = None    # YYYY-MM-DD
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
