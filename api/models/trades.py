"""
api/models/trades.py — Trade record schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


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
    risk_classification: Optional[dict[str, Any]] = None
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
    premium_exit_policy: Optional[dict[str, Any]] = None
    stage1_done: Optional[bool]
    mode: Optional[str]           # "paper" | "live" — derived from paper int column
    recap: Optional[str] = None   # auto-generated post-trade recap narrative
    # Snapshot of the bot's own chart annotations (FVG zones, BOS/TREND_CONT
    # levels, signal markers) captured at entry + exit time — see
    # database.py::close_trade()'s annotations_json merge. Loosely typed
    # (same shape as the live /api/bot/annotations/{ticker} endpoint, which
    # is also untyped dicts) rather than a strict schema, since this is a
    # straight pass-through of whatever trading/annotations.py emitted.
    annotations: Optional[list[dict[str, Any]]] = None
    # {"1Min": "with"|"against"|"neutral", "5Min": ..., "15Min": ..., "1Hour": ...} —
    # higher-timeframe trend agreement at entry, saved best-effort after the
    # trade was recorded. See trading/mtf_features.py::compute_mtf_alignment().
    mtf_bias: Optional[dict[str, str]] = None


class TradeListResponse(BaseModel):
    trades: list[Trade]
    total: int
    total_pnl: float
    win_rate: float
