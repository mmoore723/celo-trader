"""TSLA V2 Trend Continuation adapter for the paper-validation cohort."""
from __future__ import annotations

from datetime import time

import pandas as pd

from research_v2.models import Bar
from research_v2.strategies import TrendContinuation, TrendContinuationConfig
from strategies.base import Signal

STRATEGY_ID = "V2_TREND_CONT"
VALIDATED_TICKERS = frozenset({"TSLA"})
# Selected on earlier paid TSLA option data, then passed the reserved later
# segment: 10:15–11:30 ET. The start is inclusive; 11:30 belongs to the
# separate midday context and is intentionally excluded.
VALIDATED_ENTRY_START_ET = time(10, 15)
VALIDATED_ENTRY_END_ET = time(11, 30)


def is_validated_entry_time(timestamp: object) -> bool:
    """Return whether a completed signal belongs to the selected ET window.

    Live bars may arrive with a timezone while research CSVs carry naive
    Eastern timestamps. Treat naive values as ET and convert aware values to
    ET before comparing them so the paper adapter cannot drift by UTC hours.
    """
    value = pd.Timestamp(timestamp)
    if value.tzinfo is not None:
        value = value.tz_convert("America/New_York")
    return VALIDATED_ENTRY_START_ET <= value.time() < VALIDATED_ENTRY_END_ET


def evaluate(today: pd.DataFrame, ticker: str = "") -> Signal | None:
    if ticker.strip().upper() not in VALIDATED_TICKERS or "time" not in today:
        return None
    config = TrendContinuationConfig()
    if len(today) < max(config.slow_ema, config.atr_bars + 1, config.breakout_bars + 1):
        return None
    bars = tuple(Bar(pd.Timestamp(row.time).to_pydatetime(), float(row.open), float(row.high),
                     float(row.low), float(row.close), float(getattr(row, "volume", 0.0)))
                 for row in today.itertuples(index=False))
    candidate = TrendContinuation(config).evaluate(bars)
    if candidate is None:
        return None
    if not is_validated_entry_time(candidate.timestamp):
        return None
    latest = today.iloc[-1]
    return Signal(strategy_id=STRATEGY_ID,
                  direction="bullish" if candidate.side.value == "long" else "bearish",
                  confidence=0.78, rvol=float(latest.get("rvol", 0.0) or 0.0),
                  trigger_bar=pd.Timestamp(candidate.timestamp),
                  meta={**candidate.features, "v2_hypothesis": "trend_continuation", "research_only": True,
                        "v2_validated_entry_window": "10:15-11:30_ET",
                        "v2_entry_reference": float(candidate.entry_reference), "v2_stop": float(candidate.stop),
                        "v2_target": float(candidate.target),
                        "entry_bar_low": float(candidate.stop) if candidate.side.value == "long" else None,
                        "entry_bar_high": float(candidate.stop) if candidate.side.value == "short" else None})
