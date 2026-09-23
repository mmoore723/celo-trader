from __future__ import annotations

from datetime import timedelta

import pandas as pd

from research.engine.models import Side
from research.engine.strategies.trend_continuation import (
    TrendContinuation,
    TrendContinuationConfig,
)
from strategies.base import Signal
from trading.tested_strategy_research import _latest_candidate, _research_bars
from strategy_health.trend_exit import entry_state


STRATEGY_ID = "V2_TREND_CONT"
VERSION = "research.1"
SUPPORTED_TICKERS = frozenset({"SPY", "QQQ"})
_emitted: set[tuple[str, str, str]] = set()


def evaluate(
    frame: pd.DataFrame,
    ticker: str = "",
    execution_scope: str | None = None,
    now: object | None = None,
) -> Signal | None:
    symbol = ticker.strip().upper()
    if symbol not in SUPPORTED_TICKERS:
        return None
    bars = _research_bars(frame, now, 5)
    if not bars:
        return None
    strategy = TrendContinuation(TrendContinuationConfig())
    candidate = _latest_candidate(strategy, bars, research_strategy_id=STRATEGY_ID)
    if candidate is None:
        return None
    from strategies.spy_trend_continuation_v2 import _execution_scope
    scope = _execution_scope(execution_scope)
    cutoff = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    if cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("America/New_York").tz_localize(None)
    trigger = pd.Timestamp(candidate.timestamp) + timedelta(minutes=5)
    if not trigger <= cutoff < trigger + timedelta(minutes=1):
        return None
    key = (scope, symbol, candidate.timestamp.isoformat())
    if key in _emitted:
        return None
    _emitted.add(key)
    return Signal(
        strategy_id=STRATEGY_ID,
        direction="bullish" if candidate.side is Side.LONG else "bearish",
        confidence=0.70,
        rvol=0.0,
        trigger_bar=pd.Timestamp(candidate.timestamp) + timedelta(minutes=5),
        meta={
            **dict(candidate.features),
            "strategy_version": VERSION,
            "entry_timing": "completed_5m_signal_then_next_quote",
            "underlying_stop": float(candidate.stop),
            "underlying_target": float(candidate.target),
            "authored_exit_protocol": "trend_cont_structural_2r_75bars_completed5m_v1",
            "authored_exit_state": entry_state(strategy),
            "timeframe_minutes": 5,
        },
    )
