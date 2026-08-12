"""Transparent validation gates for V2 research results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from research.engine.models import Trade


@dataclass(frozen=True)
class ValidationConfig:
    min_trades: int = 30
    min_profit_factor: float = 1.15
    max_drawdown_pct: float = 15.0
    starting_capital: float = 5_000.0


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    trade_count: int
    net_pnl: float
    expectancy: float
    profit_factor: float
    max_drawdown_pct: float
    reasons: tuple[str, ...]


def validate(trades: Sequence[Trade], config: ValidationConfig = ValidationConfig()) -> ValidationResult:
    pnl = [t.net_pnl for t in trades]
    trade_count = len(pnl)
    net = sum(pnl)
    wins = sum(p for p in pnl if p > 0)
    losses = -sum(p for p in pnl if p < 0)
    profit_factor = wins / losses if losses else (float("inf") if wins else 0.0)
    equity = peak = 0.0
    max_drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    if config.starting_capital <= 0:
        raise ValueError("starting_capital must be positive")
    drawdown_pct = max_drawdown / config.starting_capital * 100
    reasons: list[str] = []
    if trade_count < config.min_trades:
        reasons.append(f"only {trade_count} trades; need {config.min_trades}")
    if net <= 0:
        reasons.append("net P&L is not positive after modeled costs")
    if profit_factor < config.min_profit_factor:
        reasons.append(f"profit factor {profit_factor:.2f} < {config.min_profit_factor:.2f}")
    if drawdown_pct > config.max_drawdown_pct:
        reasons.append(f"drawdown {drawdown_pct:.1f}% exceeds {config.max_drawdown_pct:.1f}%")
    return ValidationResult(
        passed=not reasons, trade_count=trade_count, net_pnl=round(net, 4),
        expectancy=round(net / trade_count, 4) if trade_count else 0.0,
        profit_factor=round(profit_factor, 4), max_drawdown_pct=round(drawdown_pct, 4),
        reasons=tuple(reasons),
    )
