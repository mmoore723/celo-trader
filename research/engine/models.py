"""Pure V2 domain records; intentionally independent of live-bot models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Bar:
    """A completed regular-session OHLCV bar.

    A strategy can inspect bars up through the current bar only.  The simulator
    fills a signal at the *next* bar's open, which prevents same-bar lookahead.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low must contain open and close")


@dataclass(frozen=True)
class Signal:
    """A testable setup emitted on the close of one completed bar."""

    strategy_id: str
    side: Side
    timestamp: datetime
    entry_reference: float
    stop: float
    target: float
    features: Mapping[str, float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if min(self.entry_reference, self.stop, self.target) <= 0:
            raise ValueError("signal prices must be positive")
        if self.side is Side.LONG and not (self.stop < self.entry_reference < self.target):
            raise ValueError("long signals require stop < entry < target")
        if self.side is Side.SHORT and not (self.target < self.entry_reference < self.stop):
            raise ValueError("short signals require target < entry < stop")


@dataclass(frozen=True)
class Trade:
    """Immutable simulated result, including the complete signal provenance."""

    strategy_id: str
    side: Side
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    gross_pnl: float
    net_pnl: float
    mae_pct: float
    mfe_pct: float
    exit_reason: str
    features: Mapping[str, float | str | bool]
