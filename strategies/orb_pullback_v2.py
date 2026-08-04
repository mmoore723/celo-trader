"""Adapter for the research-validated V2 opening-range pullback hypothesis.

This module makes no order decisions itself.  It translates the causal V2
research signal into the platform's normal router signal so paper execution,
journaling, MFE, and MAE use their existing audited path.
"""
from __future__ import annotations

import pandas as pd

from research_v2.models import Bar
from research_v2.strategies import OpeningRangePullback, OpeningRangePullbackConfig
from strategies.base import Signal

STRATEGY_ID = "V2_ORB_PULLBACK"


def evaluate(today: pd.DataFrame, ticker: str = "") -> Signal | None:
    if len(today) < 18 or "time" not in today:
        return None
    bars = tuple(
        Bar(pd.Timestamp(row.time).to_pydatetime(), float(row.open), float(row.high),
            float(row.low), float(row.close), float(getattr(row, "volume", 0.0)))
        for row in today.itertuples(index=False)
    )
    candidate = OpeningRangePullback(OpeningRangePullbackConfig()).evaluate(bars)
    if candidate is None:
        return None
    trigger = pd.Timestamp(candidate.timestamp)
    latest = today.iloc[-1]
    return Signal(
        strategy_id=STRATEGY_ID,
        direction="bullish" if candidate.side.value == "long" else "bearish",
        confidence=0.80,
        rvol=float(latest.get("rvol", 0.0) or 0.0),
        trigger_bar=trigger,
        # The normal entry path uses entry_bar_high/low to translate the
        # underlying invalidation level into an option-level structural stop.
        # Preserve the V2 hypothesis levels too, so the paper journal can
        # distinguish the research setup from the actual option fill.
        meta={
            **candidate.features,
            "v2_hypothesis": "opening_range_pullback",
            "research_only": True,
            "v2_entry_reference": float(candidate.entry_reference),
            "v2_stop": float(candidate.stop),
            "v2_target": float(candidate.target),
            "entry_bar_low": float(candidate.stop) if candidate.side.value == "long" else None,
            "entry_bar_high": float(candidate.stop) if candidate.side.value == "short" else None,
        },
    )
