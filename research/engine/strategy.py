"""The narrow, side-effect-free strategy contract used by V2."""

from __future__ import annotations

from typing import Protocol, Sequence

from research.engine.models import Bar, Signal


class Strategy(Protocol):
    """Emit one setup from completed bars, or ``None`` when no setup exists."""

    strategy_id: str

    def evaluate(self, bars: Sequence[Bar]) -> Signal | None:
        """Must use only ``bars`` supplied; no broker/database/global-state I/O."""
