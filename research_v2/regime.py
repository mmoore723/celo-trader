"""Past-only intraday regime labels and walk-forward regime selection.

This is deliberately not machine learning and it does not touch live routing.
It answers one narrow research question: did a candidate work only when the
market had a clearly measurable *prior* condition, and does that restriction
survive an untouched later period?
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Sequence

from research_v2.models import Bar, Side, Trade
from research_v2.simulator import Simulator
from research_v2.strategy import Strategy
from research_v2.validation import ValidationConfig, ValidationResult, validate


def prior_regime(bars: Sequence[Bar], timestamp, lookback_bars: int = 20) -> str | None:
    """Classify trend direction from completed same-session bars only.

    Efficiency is net movement divided by all bar-to-bar movement.  A high
    value means price has moved in one direction; a low value means back and
    forth movement.  This label uses no bar after ``timestamp``.
    """
    if lookback_bars < 5:
        raise ValueError("lookback_bars must be at least 5")
    session = [bar for bar in bars if bar.timestamp.date() == timestamp.date() and bar.timestamp <= timestamp]
    if len(session) < lookback_bars + 1:
        return None
    closes = [bar.close for bar in session[-(lookback_bars + 1):]]
    travel = sum(abs(current - prior) for prior, current in zip(closes, closes[1:]))
    if travel == 0:
        return "CHOPPY"
    efficiency = abs(closes[-1] - closes[0]) / travel
    if efficiency < 0.55:
        return "CHOPPY"
    return "TREND_UP" if closes[-1] > closes[0] else "TREND_DOWN"


def trade_key(trade: Trade, bars: Sequence[Bar], lookback_bars: int = 20) -> str | None:
    regime = prior_regime(bars, trade.signal_time, lookback_bars)
    return None if regime is None else f"{regime}:{trade.side.value.upper()}"


@dataclass(frozen=True)
class RegimeSelectionResult:
    selected_keys: tuple[str, ...]
    train_all: ValidationResult
    train_selected: ValidationResult
    holdout_all: ValidationResult
    holdout_selected: ValidationResult

    @property
    def promoted(self) -> bool:
        return bool(self.selected_keys) and self.train_selected.passed and self.holdout_selected.passed


def select_regimes(
    train_trades: Sequence[Trade], holdout_trades: Sequence[Trade], train_bars: Sequence[Bar], holdout_bars: Sequence[Bar],
    validation_config: ValidationConfig = ValidationConfig(), lookback_bars: int = 20,
) -> RegimeSelectionResult:
    """Select only train-proven regime/side keys, then score holdout once."""
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in train_trades:
        key = trade_key(trade, train_bars, lookback_bars)
        if key is not None:
            grouped[key].append(trade)
    selected = tuple(sorted(key for key, trades in grouped.items() if validate(trades, validation_config).passed))
    train_selected = [trade for trade in train_trades if trade_key(trade, train_bars, lookback_bars) in selected]
    holdout_selected = [trade for trade in holdout_trades if trade_key(trade, holdout_bars, lookback_bars) in selected]
    return RegimeSelectionResult(
        selected, validate(train_trades, validation_config), validate(train_selected, validation_config),
        validate(holdout_trades, validation_config), validate(holdout_selected, validation_config),
    )


def run_regime_walk_forward(
    bars: Sequence[Bar], split_time, strategy_factory: Callable[[], Strategy], simulator: Simulator,
    validation_config: ValidationConfig = ValidationConfig(), lookback_bars: int = 20,
) -> RegimeSelectionResult:
    train_bars = tuple(bar for bar in bars if bar.timestamp < split_time)
    holdout_bars = tuple(bar for bar in bars if bar.timestamp >= split_time)
    if len(train_bars) < 3 or len(holdout_bars) < 3:
        raise ValueError("both train and holdout segments need at least three bars")
    return select_regimes(simulator.run(train_bars, strategy_factory()), simulator.run(holdout_bars, strategy_factory()),
                          train_bars, holdout_bars, validation_config, lookback_bars)
