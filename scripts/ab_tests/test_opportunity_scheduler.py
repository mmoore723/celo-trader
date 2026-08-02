"""Focused causal-behavior checks for trading.opportunity_scheduler.

Run with:
    python scripts/ab_tests/test_opportunity_scheduler.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from trading.opportunity_scheduler import due_ticker, select


@dataclass
class Signal:
    strategy_id: str
    direction: str
    confidence: float
    tier: str


def main() -> None:
    state: dict = {}
    start = datetime(2026, 8, 3, 10, 0)
    first = Signal("MID_BRK", "bearish", 0.721, "opportunity")
    stronger = Signal("FVG", "bullish", 0.739, "opportunity")
    main_signal = Signal("TREND_CONT", "bullish", 0.751, "main")

    # First opportunity reserves a short research window, not an order.
    outcome = select(state, "SPY", [first], start)
    assert outcome.action == "waiting" and outcome.event == "started"
    assert state["opportunity_scheduler"]["ticker"] == "SPY"

    # A stronger *observed* candidate wins rank but cannot extend the window.
    outcome = select(state, "QQQ", [stronger], start + timedelta(minutes=5))
    assert outcome.action == "waiting" and outcome.event == "replaced"
    assert state["opportunity_scheduler"]["ticker"] == "QQQ"
    assert due_ticker(state, start + timedelta(minutes=14)) is None
    assert due_ticker(state, start + timedelta(minutes=15)) == "QQQ"

    # At expiry it must still be present; no stale entry is permitted.
    outcome = select(state, "QQQ", [stronger], start + timedelta(minutes=15))
    assert outcome.action == "select" and outcome.event == "confirmed"
    assert outcome.signal is stronger and not state["opportunity_scheduler"]

    # A main-tier signal is never delayed and explicitly preempts the window.
    select(state, "SPY", [first], start + timedelta(minutes=20))
    outcome = select(state, "AAPL", [main_signal], start + timedelta(minutes=21))
    assert outcome.action == "select" and outcome.event == "main_preempted"
    assert outcome.signal is main_signal and not state["opportunity_scheduler"]

    # If confirmation vanishes at expiry, the candidate is discarded.
    select(state, "NVDA", [first], start + timedelta(minutes=30))
    outcome = select(state, "NVDA", [], start + timedelta(minutes=45))
    assert outcome.action == "expired" and outcome.event == "confirmation_lost"
    assert not state["opportunity_scheduler"]
    print("opportunity scheduler: PASS")


if __name__ == "__main__":
    main()
