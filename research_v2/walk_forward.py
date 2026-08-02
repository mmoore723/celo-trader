"""Walk-forward evaluation: design on the past, judge on untouched bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from research_v2.models import Bar, Trade
from research_v2.simulator import Simulator
from research_v2.strategy import Strategy
from research_v2.validation import ValidationConfig, ValidationResult, validate


@dataclass(frozen=True)
class WalkForwardResult:
    split_time: datetime
    train_trades: tuple[Trade, ...]
    holdout_trades: tuple[Trade, ...]
    train_validation: ValidationResult
    holdout_validation: ValidationResult

    @property
    def promoted(self) -> bool:
        """Both periods must independently pass; no blended-stat rescue."""
        return self.train_validation.passed and self.holdout_validation.passed


def run_walk_forward(
    bars: Sequence[Bar],
    split_time: datetime,
    strategy_factory: Callable[[], Strategy],
    simulator: Simulator,
    validation_config: ValidationConfig = ValidationConfig(),
) -> WalkForwardResult:
    """Run fresh strategy instances on non-overlapping design and holdout bars."""
    train = tuple(bar for bar in bars if bar.timestamp < split_time)
    holdout = tuple(bar for bar in bars if bar.timestamp >= split_time)
    if len(train) < 3 or len(holdout) < 3:
        raise ValueError("both train and holdout segments need at least three bars")
    train_trades = tuple(simulator.run(train, strategy_factory()))
    holdout_trades = tuple(simulator.run(holdout, strategy_factory()))
    return WalkForwardResult(
        split_time=split_time,
        train_trades=train_trades,
        holdout_trades=holdout_trades,
        train_validation=validate(train_trades, validation_config),
        holdout_validation=validate(holdout_trades, validation_config),
    )
