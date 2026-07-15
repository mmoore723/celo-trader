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
    day_start_balance: float         # Alpaca equity captured once at bot startup — never derived
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
    last_eval_contracts: Optional[int] = None
    last_eval_opt_type: Optional[str] = None
    last_eval_ticker: Optional[str] = None
    # Maintenance mode — set by admin to halt all trading and show maintenance screen
    maintenance_mode: bool = False
    maintenance_message: str = ""


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
    recap: Optional[str] = None   # auto-generated post-trade recap narrative


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
    ifvg_enabled: bool = True    # Inverted Fair Value Gap — zone-flip reversal
    bos_mss_enabled: bool
    chan_break_enabled: bool = True
    mid_brk_enabled: bool = True
    trend_cont_enabled: bool = True
    signal_only_mode: bool = False  # True = bot alerts but never places orders
    # ── Trade parameters (user-tunable without touching code) ─────────────────
    orb_stage1_gain_pct: float = 50.0   # Stage-1 profit target as % of entry
    orb_stop_loss_pct:   float = 20.0   # Option premium stop-loss as % of entry
    spread_gate_pct:     float = 25.0   # Max bid-ask spread as % of mid
    vol_roc_threshold:   float = 0.50   # Volume ROC veto threshold


# ── Analytics ─────────────────────────────────────────────────────────────────

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


# ── News ──────────────────────────────────────────────────────────────────────

class NewsArticle(BaseModel):
    id: Optional[int] = None
    headline: str
    summary: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[str] = None
    symbols: list[str] = []


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
    start_date: Optional[str] = None   # YYYY-MM-DD; if provided with end_date, overrides months
    end_date: Optional[str] = None     # YYYY-MM-DD
    starting_capital: float = 1000.0
    direction: str = "both"            # "both" | "calls_only" | "puts_only"
    risk_pct: Optional[float] = None   # flat override e.g. 0.05 = 5%; None = live 4-tier ladder


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


# ── Reconciliation ───────────────────────────────────────────────────────────

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
    alpaca_equity: Optional[float]          # current Alpaca account equity
    day_start_balance: Optional[float]      # captured at bot start
    bot_session_pnl: float                  # sum of DB realized_pnl for the date
    alpaca_session_pnl: Optional[float]     # equity - day_start
    equity_gap: Optional[float]             # bot_session_pnl - alpaca_session_pnl
    trades: list[ReconcileRow]
    unmatched_alpaca_orders: list[AlpacaOrder]  # Alpaca orders with no DB match


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
