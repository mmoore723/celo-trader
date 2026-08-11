"""TSLA V2 Trend Continuation adapter for the paper-validation cohort."""
from __future__ import annotations

import pandas as pd

from research_v2.models import Bar
from research_v2.strategies import TrendContinuation, TrendContinuationConfig
from strategies.base import Signal

STRATEGY_ID = "V2_TREND_CONT"
VALIDATED_TICKERS = frozenset({"TSLA"})


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
    latest = today.iloc[-1]
    return Signal(strategy_id=STRATEGY_ID,
                  direction="bullish" if candidate.side.value == "long" else "bearish",
                  confidence=0.78, rvol=float(latest.get("rvol", 0.0) or 0.0),
                  trigger_bar=pd.Timestamp(candidate.timestamp),
                  meta={**candidate.features, "v2_hypothesis": "trend_continuation", "research_only": True,
                        "v2_entry_reference": float(candidate.entry_reference), "v2_stop": float(candidate.stop),
                        "v2_target": float(candidate.target),
                        "entry_bar_low": float(candidate.stop) if candidate.side.value == "long" else None,
                        "entry_bar_high": float(candidate.stop) if candidate.side.value == "short" else None})
